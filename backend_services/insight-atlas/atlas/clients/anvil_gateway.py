"""Anvil analytics reader.

Atlas never receives ClickHouse credentials. In the default (gateway
mediated) topology the Insight Gateway authenticates this client and
forwards the narrow feature query to Anvil, rewriting the path on the
way. When Anvil runs alongside Atlas there is no gateway to do that
rewrite, so the path prefix is configurable — see
`Settings.anvil_features_path_prefix`.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

# Gateway-facing route. The gateway maps it onto the `/internal/features`
# path Anvil actually serves; a direct-to-Anvil deployment must override
# this or every feature read 404s.
DEFAULT_FEATURES_PATH_PREFIX = "/internal/anvil/features"

# What Anvil itself serves (anvil/runtime/health.py). Exported so a
# direct deployment references the real value instead of retyping it.
DIRECT_FEATURES_PATH_PREFIX = "/internal/features"

# Header the gateway expects from Atlas.
DEFAULT_API_KEY_HEADER = "X-Atlas-Anvil-Key"

# Header Anvil itself checks (anvil/runtime/health.py compares
# `x-anvil-api-key`). The gateway translates between the two; a direct
# deployment has nobody to do that, and the mismatch fails as a 401 —
# indistinguishable from a wrong key, which is a genuinely confusing
# thing to debug.
DIRECT_API_KEY_HEADER = "x-anvil-api-key"


class AnvilGatewayError(Exception):
    pass


class AnvilGatewayReader:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 8.0,
        features_path_prefix: str = DEFAULT_FEATURES_PATH_PREFIX,
        api_key_header: str = DEFAULT_API_KEY_HEADER,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Anvil Gateway base URL is required")
        if len(api_key.strip()) < 32:
            raise ValueError("Anvil Gateway API key must be at least 32 characters")
        # Strip BEFORE validating: "/" and "//" are non-empty strings
        # that normalise to nothing, and would build `/matches/{id}` —
        # a real route on some other service, queried silently.
        prefix = features_path_prefix.strip().strip("/")
        if not prefix:
            raise ValueError("Anvil features path prefix is required")
        # Normalised once here so callers may pass it with or without
        # surrounding slashes and the built URL is identical either way.
        self._prefix = f"/{prefix}"
        header = api_key_header.strip()
        if not header:
            raise ValueError("Anvil API key header is required")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={header: api_key},
        )
        self._cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _features(
        self,
        *,
        match_id: UUID,
        as_of: datetime,
        pressure_window_seconds: int = 300,
        market_window_seconds: int = 600,
        signal_window_seconds: int = 600,
        series_limit: int = 6,
    ) -> dict[str, Any]:
        cache_key = (
            match_id,
            as_of.isoformat(),
            pressure_window_seconds,
            market_window_seconds,
            signal_window_seconds,
            series_limit,
        )
        cached = self._cache.get(cache_key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        path = f"{self._prefix}/matches/{quote(str(match_id), safe='')}"
        try:
            response = await self._client.get(
                path,
                params={
                    "as_of": as_of.isoformat(),
                    "pressure_window_seconds": pressure_window_seconds,
                    "market_window_seconds": market_window_seconds,
                    "signal_window_seconds": signal_window_seconds,
                    "series_limit": series_limit,
                },
            )
        except httpx.HTTPError as exc:
            raise AnvilGatewayError(str(exc)) from exc
        if response.status_code >= 400:
            raise AnvilGatewayError(
                f"http_{response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AnvilGatewayError("invalid Anvil Gateway response")
        self._cache = {cache_key: (time.monotonic() + 1.0, payload)}
        return payload

    async def pressure_means(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> tuple[float | None, float | None]:
        data = await self._features(
            match_id=match_id,
            as_of=as_of,
            pressure_window_seconds=window_seconds,
        )
        pressure = data.get("pressure") or {}
        return (_float_or_none(pressure.get("home")), _float_or_none(pressure.get("away")))

    async def consensus_movement(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> tuple[float | None, float | None]:
        data = await self._features(
            match_id=match_id,
            as_of=as_of,
            market_window_seconds=window_seconds,
        )
        market = data.get("market") or {}
        return (
            _float_or_none(market.get("volatility")),
            _float_or_none(market.get("consensus_shift")),
        )

    async def signal_count(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> int:
        data = await self._features(
            match_id=match_id,
            as_of=as_of,
            signal_window_seconds=window_seconds,
        )
        try:
            return int(data.get("signal_count") or 0)
        except (TypeError, ValueError):
            return 0

    async def pressure_series(
        self, *, match_id: UUID, as_of: datetime, limit: int
    ) -> list[tuple[float, float]]:
        data = await self._features(
            match_id=match_id,
            as_of=as_of,
            series_limit=limit,
        )
        out: list[tuple[float, float]] = []
        for row in data.get("pressure_series") or []:
            if not isinstance(row, dict):
                continue
            home = _float_or_none(row.get("home"))
            away = _float_or_none(row.get("away"))
            if home is not None and away is not None:
                out.append((home, away))
        return out

    async def match_minute(self, *, match_id: UUID, as_of: datetime) -> int | None:
        data = await self._features(match_id=match_id, as_of=as_of)
        try:
            value = data.get("minute")
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
