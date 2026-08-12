"""Feature pipeline — assembles all builders into one FeatureSnapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from atlas.contracts import FeatureWindowOrigin
from atlas.features.builders import (
    AnalyticsReader,
    SentimentReader,
    build_late_pressure,
    build_market,
    build_momentum,
    build_pressure,
    build_sentiment,
    build_signal_density,
)
from atlas.features.snapshot import FeatureSnapshot


async def build_snapshot(
    *,
    match_id: UUID,
    competition_id: UUID | None,
    as_of: datetime | None,
    schema_version: int,
    analytics: AnalyticsReader,
    sentiment: SentimentReader,
    feature_window_origin: FeatureWindowOrigin = FeatureWindowOrigin.rolling,
) -> FeatureSnapshot:
    """Assemble a FeatureSnapshot from upstream readers.

    Sprint 0.1: `feature_window_origin` is forwarded to the snapshot so
    downstream debugging can tell apart worker-driven (`rolling`) from
    on-demand (`live`) builds. Callers MUST set it correctly — leaving
    the default to `rolling` is appropriate for the periodic worker;
    REST handlers should pass `FeatureWindowOrigin.live`.
    """
    ts = as_of or datetime.now(timezone.utc)
    features: dict[str, Any] = {}
    features.update(await build_pressure(analytics, match_id=match_id, as_of=ts))
    features.update(await build_market(analytics, match_id=match_id, as_of=ts))
    features.update(await build_signal_density(analytics, match_id=match_id, as_of=ts))
    features.update(await build_momentum(analytics, match_id=match_id, as_of=ts))
    features.update(await build_late_pressure(analytics, match_id=match_id, as_of=ts))
    features.update(await build_sentiment(sentiment, match_id=match_id, as_of=ts))
    # engagement_rate removed in schema v2 — see definitions.py comment.

    minute = await analytics.match_minute(match_id=match_id, as_of=ts)

    return FeatureSnapshot(
        match_id=match_id,
        competition_id=competition_id,
        minute=minute,
        ts=ts,
        schema_version=schema_version,
        feature_window_origin=feature_window_origin,
        features={k: float(v) for k, v in features.items()},
    ).with_defaults()
