from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis

from anvil.streaming.jsonx import dumps


def utcnow():
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class DlqWriter:
    redis_client: Redis
    dlq_key: str
    max_error_chars: int = 500

    async def push(
        self,
        *,
        source_stream: str,
        group: str,
        message_id: str,
        raw_fields: dict,
        error: str,
        attempts: int,
        source: str,
    ) -> None:
        payload = {
            "source_stream": source_stream,
            "group": group,
            "message_id": message_id,
            "attempts": attempts,
            "source": source,
            "error": (error[: self.max_error_chars] if error else ""),
            "raw_fields": self._sanitize_raw_fields(raw_fields),
            "ts_dlq": utcnow().isoformat(),
        }
        # DLQ é stream também (melhor que list) — permite replay
        await self.redis_client.xadd(
            name=self.dlq_key,
            fields={b"payload": dumps(payload)},
            maxlen=200_000,
            approximate=True,
        )

    def _sanitize_raw_fields(self, fields: dict) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in fields.items():
            key = self._b2s(raw_key)
            value = raw_value if isinstance(raw_value, (bytes, bytearray)) else str(raw_value).encode()

            if key == "payload":
                sanitized["payload_bytes"] = len(value)
                sanitized["payload_sha256"] = hashlib.sha256(bytes(value)).hexdigest()
                continue

            if key in {"event_id", "match_id", "region_code", "event_type", "match_version", "ts_ingest"}:
                sanitized[key] = self._b2s(value, max_chars=128)
            else:
                sanitized[f"{key}_bytes"] = len(value)
                sanitized[f"{key}_sha256"] = hashlib.sha256(bytes(value)).hexdigest()

        return sanitized

    @staticmethod
    def _b2s(x, *, max_chars: int = 256):
        if isinstance(x, (bytes, bytearray)):
            return x.decode(errors="replace")[:max_chars]
        return str(x)[:max_chars]
