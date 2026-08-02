"""Feature registry — single source of truth for what Atlas observes.

Each `FeatureDef` declares:
  * name (snake_case, stable across schema versions of the same kind)
  * source (which event stream / aggregate it derives from)
  * window (rolling window used at build time)
  * range (expected numeric envelope — used for z-score normalisation
           in the explainer)
  * default (value used when the source has no data)

Schema versioning: bumping `FEATURE_SCHEMA_VERSION` in settings + adding
or removing entries here is the canonical way to evolve features. Models
trained against a different schema_version are not used for inference;
the registry filters them out.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDef:
    name: str
    source: str
    window_seconds: int  # 0 means "snapshot, no window"
    default: float
    low: float
    high: float
    description: str


_DEFINITIONS: list[FeatureDef] = [
    FeatureDef(
        name="pressure_home_5m",
        source="metric_ticks",
        window_seconds=300,
        default=0.5,
        low=0.0,
        high=1.0,
        description="Mean of human_pressure_home over last 5min.",
    ),
    FeatureDef(
        name="pressure_away_5m",
        source="metric_ticks",
        window_seconds=300,
        default=0.5,
        low=0.0,
        high=1.0,
        description="Mean of human_pressure_away over last 5min.",
    ),
    FeatureDef(
        name="pressure_delta",
        source="derived",
        window_seconds=300,
        default=0.0,
        low=-1.0,
        high=1.0,
        description="pressure_home_5m − pressure_away_5m.",
    ),
    FeatureDef(
        name="market_volatility",
        source="market_snapshots",
        window_seconds=600,
        default=0.0,
        low=0.0,
        high=0.5,
        description="Std-dev of consensus odd movement over last 10min.",
    ),
    FeatureDef(
        name="consensus_shift",
        source="market_snapshots",
        window_seconds=600,
        default=0.0,
        low=-1.0,
        high=1.0,
        description="Net change in home-consensus odd over last 10min.",
    ),
    FeatureDef(
        name="signal_density",
        source="human_signals",
        window_seconds=600,
        default=0.0,
        low=0.0,
        high=20.0,
        description="Signals per minute in last 10min.",
    ),
    FeatureDef(
        name="community_confidence",
        source="sentiment",
        window_seconds=0,
        default=0.5,
        low=0.0,
        high=1.0,
        description="Latest aggregated community sentiment value.",
    ),
    FeatureDef(
        name="sentiment_delta",
        source="sentiment",
        window_seconds=300,
        default=0.0,
        low=-1.0,
        high=1.0,
        description="Change in community sentiment over last 5min.",
    ),
    # `engagement_rate` removed in feature schema v2 (Sprint 0.1).
    # The v1 builder always returned the registry default (0.0) because
    # the upstream feed_reactions rollup never landed — the feature was
    # polluting the vector with a constant value, biasing distance
    # metrics in cluster + anomaly. Re-introduce only when a real
    # rollup exists.
    FeatureDef(
        name="momentum_score",
        source="derived",
        window_seconds=600,
        default=0.0,
        low=-1.0,
        high=1.0,
        description="Net pressure delta over last 6 metric ticks.",
    ),
    FeatureDef(
        name="market_stability_score",
        source="derived",
        window_seconds=600,
        default=1.0,
        low=0.0,
        high=1.0,
        description="1 − normalised market_volatility.",
    ),
    FeatureDef(
        name="late_pressure_score",
        source="derived",
        window_seconds=0,
        default=0.0,
        low=0.0,
        high=1.0,
        description="Average pressure after minute 60; 0 before that minute.",
    ),
]


registry: dict[str, FeatureDef] = {f.name: f for f in _DEFINITIONS}

# Canonical ordering — ML feature vectors are positional, so this list
# is the authoritative ordering of columns. Anything reading vectors
# must use this order.
FEATURE_NAMES: list[str] = [f.name for f in _DEFINITIONS]


def defaults() -> dict[str, float]:
    return {f.name: f.default for f in _DEFINITIONS}
