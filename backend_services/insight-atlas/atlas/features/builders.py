"""Feature builders.

Each builder takes a `(match_id, as_of_ts)` plus an `AnalyticsReader`
and returns the value of one feature. They are intentionally pure
functions — no mutation, no I/O outside the reader interface.

The reader is a thin protocol that lets unit tests inject synthetic
windowed aggregates. In production it calls Anvil through Insight Gateway.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from atlas.features.definitions import registry


class AnalyticsReader(Protocol):
    """Narrow analytical read surface consumed by feature builders."""

    async def pressure_means(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> tuple[float | None, float | None]:
        """Returns (home_mean, away_mean)."""
        ...

    async def consensus_movement(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> tuple[float | None, float | None]:
        """Returns (std_dev, net_shift). Inputs are home consensus odds."""
        ...

    async def signal_count(
        self, *, match_id: UUID, as_of: datetime, window_seconds: int
    ) -> int:
        ...

    async def pressure_series(
        self, *, match_id: UUID, as_of: datetime, limit: int
    ) -> list[tuple[float, float]]:
        """Recent (home, away) pressure pairs newest-last."""
        ...

    async def match_minute(self, *, match_id: UUID, as_of: datetime) -> int | None:
        ...


class SentimentReader(Protocol):
    """Sentiment read port; only what feature builders consume.
    Implementations live in `atlas/clients/sentiment.py`."""

    async def latest_value(self, match_id: UUID) -> float | None: ...

    async def value_5m_ago(self, match_id: UUID, as_of: datetime) -> float | None: ...


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


async def build_pressure(
    analytics: AnalyticsReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    """Builds pressure_home_5m, pressure_away_5m, pressure_delta together
    because they share one query."""
    home, away = await analytics.pressure_means(
        match_id=match_id, as_of=as_of, window_seconds=300
    )
    h = home if home is not None else registry["pressure_home_5m"].default
    a = away if away is not None else registry["pressure_away_5m"].default
    return {
        "pressure_home_5m": h,
        "pressure_away_5m": a,
        "pressure_delta": h - a,
    }


async def build_market(
    analytics: AnalyticsReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    std, shift = await analytics.consensus_movement(
        match_id=match_id, as_of=as_of, window_seconds=600
    )
    s = std if std is not None else registry["market_volatility"].default
    sh = shift if shift is not None else registry["consensus_shift"].default
    return {
        "market_volatility": s,
        "consensus_shift": sh,
        "market_stability_score": _stability(s),
    }


async def build_signal_density(
    analytics: AnalyticsReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    count = await analytics.signal_count(
        match_id=match_id, as_of=as_of, window_seconds=600
    )
    return {"signal_density": float(count) / 10.0}  # per-minute


async def build_momentum(
    analytics: AnalyticsReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    series = await analytics.pressure_series(match_id=match_id, as_of=as_of, limit=6)
    if len(series) < 2:
        return {"momentum_score": registry["momentum_score"].default}
    earliest = series[0][0] - series[0][1]
    latest = series[-1][0] - series[-1][1]
    delta = max(-1.0, min(1.0, latest - earliest))
    return {"momentum_score": delta}


async def build_late_pressure(
    analytics: AnalyticsReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    minute = await analytics.match_minute(match_id=match_id, as_of=as_of)
    if minute is None or minute < 60:
        return {"late_pressure_score": registry["late_pressure_score"].default}
    home, away = await analytics.pressure_means(
        match_id=match_id, as_of=as_of, window_seconds=300
    )
    if home is None and away is None:
        return {"late_pressure_score": registry["late_pressure_score"].default}
    return {"late_pressure_score": ((home or 0.0) + (away or 0.0)) / 2.0}


async def build_sentiment(
    sentiment: SentimentReader, *, match_id: UUID, as_of: datetime
) -> dict[str, float]:
    latest = await sentiment.latest_value(match_id)
    prior = await sentiment.value_5m_ago(match_id, as_of)
    out: dict[str, float] = {}
    out["community_confidence"] = (
        latest if latest is not None else registry["community_confidence"].default
    )
    if latest is not None and prior is not None:
        out["sentiment_delta"] = latest - prior
    else:
        out["sentiment_delta"] = registry["sentiment_delta"].default
    return out


def _stability(volatility: float) -> float:
    """1 − clamp(volatility / high). Higher volatility ⇒ lower stability."""
    hi = registry["market_volatility"].high
    if hi <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (volatility / hi)))
