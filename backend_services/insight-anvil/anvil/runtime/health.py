from __future__ import annotations

import asyncio
import json
import logging
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID


logger = logging.getLogger(__name__)


ReadinessCheck = Callable[[], Awaitable[tuple[bool, dict]]]
FeatureSnapshot = Callable[..., Awaitable[dict]]


@dataclass(frozen=True)
class HealthServerConfig:
    host: str
    port: int
    readiness_timeout_seconds: float


class HealthServer:
    """
    Minimal HTTP server for Kubernetes probes.

    Endpoints:
    - /live: process is alive
    - /ready: dependencies required for consuming/publishing are reachable
    """

    def __init__(
        self,
        *,
        cfg: HealthServerConfig,
        readiness_check: ReadinessCheck,
        feature_api_key: str = "",
        feature_snapshot: FeatureSnapshot | None = None,
    ):
        self._cfg = cfg
        self._readiness_check = readiness_check
        self._feature_api_key = feature_api_key
        self._feature_snapshot = feature_snapshot
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self._cfg.host,
            port=self._cfg.port,
        )
        logger.info("health_server_started", extra={"host": self._cfg.host, "port": self._cfg.port})

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            method, target = self._extract_request(request_line)
            headers = await self._read_headers(reader)
            parsed = urlsplit(target)
            path = parsed.path

            if path == "/live":
                await self._write_json(writer, 200, {"status": "ok", "ts": self._now()})
                return

            if path == "/ready":
                ready, details = await asyncio.wait_for(
                    self._readiness_check(),
                    timeout=self._cfg.readiness_timeout_seconds,
                )
                await self._write_json(
                    writer,
                    200 if ready else 503,
                    {"status": "ready" if ready else "not_ready", "ts": self._now(), **details},
                )
                return

            if path == "/metrics":
                # Imported lazily so a missing prometheus_client only impacts
                # the /metrics endpoint, not the liveness probe.
                from anvil.runtime.consumer_metrics import render_metrics

                body, content_type = render_metrics()
                await self._write_raw(writer, 200, content_type, body)
                return

            prefix = "/internal/features/matches/"
            if method == "GET" and path.startswith(prefix):
                if not self._feature_api_key or self._feature_snapshot is None:
                    await self._write_json(writer, 503, {"detail": "feature_api_disabled"})
                    return
                supplied = headers.get("x-anvil-api-key", "")
                if not hmac.compare_digest(supplied, self._feature_api_key):
                    await self._write_json(writer, 401, {"detail": "invalid_api_key"})
                    return
                query = parse_qs(parsed.query)
                try:
                    payload = await self._feature_snapshot(
                        match_id=UUID(path[len(prefix):]),
                        as_of=datetime.fromisoformat(
                            _first(query, "as_of").replace("Z", "+00:00")
                        ),
                        pressure_window_seconds=_positive_int(
                            query, "pressure_window_seconds", 300, 3600
                        ),
                        market_window_seconds=_positive_int(
                            query, "market_window_seconds", 600, 3600
                        ),
                        signal_window_seconds=_positive_int(
                            query, "signal_window_seconds", 600, 3600
                        ),
                        series_limit=_positive_int(query, "series_limit", 6, 100),
                    )
                except (ValueError, KeyError) as exc:
                    await self._write_json(writer, 400, {"detail": str(exc)})
                    return
                await self._write_json(writer, 200, payload)
                return

            await self._write_json(writer, 404, {"status": "not_found", "ts": self._now()})
        except asyncio.TimeoutError:
            await self._write_json(writer, 503, {"status": "timeout", "ts": self._now()})
        except Exception:
            logger.exception("health_request_failed")
            await self._write_json(writer, 500, {"status": "error", "ts": self._now()})
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _extract_request(request_line: bytes) -> tuple[str, str]:
        try:
            parts = request_line.decode("ascii", errors="replace").split()
        except Exception:
            return "", "/"
        if len(parts) < 2:
            return "", "/"
        return parts[0].upper(), parts[1]

    @staticmethod
    async def _read_headers(reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
            if line in (b"\r\n", b"\n", b""):
                return headers
            name, _, value = line.decode("latin-1").partition(":")
            if name and value:
                headers[name.strip().lower()] = value.strip()

    @staticmethod
    async def _write_json(writer: asyncio.StreamWriter, status: int, payload: dict) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        await HealthServer._write_raw(writer, status, "application/json", body)

    @staticmethod
    async def _write_raw(
        writer: asyncio.StreamWriter,
        status: int,
        content_type: str,
        body: bytes,
    ) -> None:
        reason = {
            200: "OK",
            404: "Not Found",
            400: "Bad Request",
            401: "Unauthorized",
            500: "Internal Server Error",
            503: "Service Unavailable",
        }.get(status, "OK")
        headers = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(headers + body)
        await writer.drain()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values or not values[0]:
        raise KeyError(f"{key} is required")
    return values[0]


def _positive_int(
    query: dict[str, list[str]], key: str, default: int, maximum: int
) -> int:
    values = query.get(key)
    value = int(values[0]) if values else default
    if value <= 0 or value > maximum:
        raise ValueError(f"{key} must be between 1 and {maximum}")
    return value
