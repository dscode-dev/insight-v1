"""Gateway-mediated Anvil analytics reader.

Atlas never receives ClickHouse credentials. The Insight Gateway authenticates
this client and forwards the narrow feature query to Anvil.
"""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx


class AnvilGatewayError(Exception):
    pass


class AnvilGatewayReader:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 8.0,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Anvil Gateway base URL is required")
        if len(api_key.strip()) < 32:
            raise ValueError("Anvil Gateway API key must be at least 32 characters")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={"X-Atlas-Anvil-Key": api_key},
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
        path = f"/internal/anvil/features/matches/{quote(str(match_id), safe='')}"
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
