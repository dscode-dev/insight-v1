"""Trend domain model — Sprint 0 (Trend Intelligence Foundation).

A Trend is Atlas's primary output: a structured, typed statement that
something meaningful is developing in a match, derived from correlated
signals. Trends are descriptive intelligence — never predictions, never
posts, never user-facing copy. Downstream services (Nexus → Atrium →
Azteca) consume the structured event; Atlas knows nothing about them.

Taxonomy: five detector families ("engines" in platform vocabulary),
seventeen V1 trend types. The enums are additive-only; string values
are the wire contract.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from atlas.odds.models import OddsTick
from atlas.signal_engine import Signal

if TYPE_CHECKING:
    from atlas.similarity.contracts import SimilarityContext

# v2 (Sprint 1.5): adds publish_score, publication_tier,
# lifecycle_state, correlation_ids. Strictly additive over v1.
# v3 (Sprint 2): adds meaning, meaning_category, meaning_confidence
# (interpretation layer) + timeline (lifecycle previous states) +
# pattern (statistical pattern memory). Strictly additive over v2 —
# every v1 and v2 field is preserved.
# v4 (Sprint 1.5 — Intelligence Maturity): adds historical_context,
# market_memory, competition_context, regime, continuation. Strictly
# additive over v3 — every prior field is preserved.
TREND_SCHEMA_VERSION = "v4"


class TrendCategory(str, enum.Enum):
    """Detector family. Platform codenames map to analytical domains."""

    ninja = "ninja"          # market intelligence
    pulse = "pulse"          # momentum / in-match dynamics
    oracle = "oracle"        # historical comparison
    sentinel = "sentinel"    # impact / risk
    echo = "echo"            # narrative / community
    fusion = "fusion"        # correlated multi-trend intelligence (Sprint 1.5)
    meta = "meta"            # recurring cross-match intelligence (Maturity 1.5)


class TrendType(str, enum.Enum):
    # Ninja — market trends.
    market_shift = "market_shift"
    market_acceleration = "market_acceleration"
    market_disagreement = "market_disagreement"
    market_anomaly = "market_anomaly"
    # Ninja — market intelligence (Magnus Absorption, Sprint 1).
    market_consensus_growing = "MARKET_CONSENSUS_GROWING"
    market_consensus_weakening = "MARKET_CONSENSUS_WEAKENING"
    market_divergence = "MARKET_DIVERGENCE"
    market_fragmentation = "MARKET_FRAGMENTATION"
    confidence_acceleration = "CONFIDENCE_ACCELERATION"
    confidence_decay = "CONFIDENCE_DECAY"
    volatility_increase = "VOLATILITY_INCREASE"
    volatility_decrease = "VOLATILITY_DECREASE"
    sharp_market_move = "SHARP_MARKET_MOVE"
    # Pulse — momentum trends.
    momentum_shift = "momentum_shift"
    pressure_building = "pressure_building"
    tempo_change = "tempo_change"
    dominance_pattern = "dominance_pattern"
    # Oracle — historical trends.
    historical_pattern = "historical_pattern"
    historical_similarity = "historical_similarity"
    historical_deviation = "historical_deviation"
    # Sentinel — impact trends.
    impact_assessment = "impact_assessment"
    game_state_change = "game_state_change"
    risk_increase = "risk_increase"
    # Echo — narrative trends.
    narrative_conflict = "narrative_conflict"
    sentiment_shift = "sentiment_shift"
    community_signal = "community_signal"
    # Fusion — correlated trends (Sprint 1.5). First-class trends
    # produced by the correlation engine from co-occurring members.
    market_conviction = "market_conviction"
    imminent_breakthrough = "imminent_breakthrough"
    risk_escalation = "risk_escalation"
    narrative_divergence = "narrative_divergence"
    # Fusion — market-intelligence correlations (Magnus Absorption).
    market_uncertainty = "MARKET_UNCERTAINTY"
    market_reaction = "MARKET_REACTION"
    # Meta — recurring intelligence patterns (Maturity Sprint 1.5).
    market_underestimation = "MARKET_UNDERESTIMATION"
    market_overestimation = "MARKET_OVERESTIMATION"
    recurring_volatility = "RECURRING_VOLATILITY"
    recurring_confidence_failure = "RECURRING_CONFIDENCE_FAILURE"
    recurring_sharp_reversal = "RECURRING_SHARP_REVERSAL"
    # Fusion — intelligence-maturity correlations (Maturity Sprint 1.5).
    strong_historical_alignment = "STRONG_HISTORICAL_ALIGNMENT"
    structural_volatility = "STRUCTURAL_VOLATILITY"
    market_correction = "MARKET_CORRECTION"


CATEGORY_OF: dict[TrendType, TrendCategory] = {
    TrendType.market_shift: TrendCategory.ninja,
    TrendType.market_acceleration: TrendCategory.ninja,
    TrendType.market_disagreement: TrendCategory.ninja,
    TrendType.market_anomaly: TrendCategory.ninja,
    TrendType.market_consensus_growing: TrendCategory.ninja,
    TrendType.market_consensus_weakening: TrendCategory.ninja,
    TrendType.market_divergence: TrendCategory.ninja,
    TrendType.market_fragmentation: TrendCategory.ninja,
    TrendType.confidence_acceleration: TrendCategory.ninja,
    TrendType.confidence_decay: TrendCategory.ninja,
    TrendType.volatility_increase: TrendCategory.ninja,
    TrendType.volatility_decrease: TrendCategory.ninja,
    TrendType.sharp_market_move: TrendCategory.ninja,
    TrendType.momentum_shift: TrendCategory.pulse,
    TrendType.pressure_building: TrendCategory.pulse,
    TrendType.tempo_change: TrendCategory.pulse,
    TrendType.dominance_pattern: TrendCategory.pulse,
    TrendType.historical_pattern: TrendCategory.oracle,
    TrendType.historical_similarity: TrendCategory.oracle,
    TrendType.historical_deviation: TrendCategory.oracle,
    TrendType.impact_assessment: TrendCategory.sentinel,
    TrendType.game_state_change: TrendCategory.sentinel,
    TrendType.risk_increase: TrendCategory.sentinel,
    TrendType.narrative_conflict: TrendCategory.echo,
    TrendType.sentiment_shift: TrendCategory.echo,
    TrendType.community_signal: TrendCategory.echo,
    TrendType.market_conviction: TrendCategory.fusion,
    TrendType.imminent_breakthrough: TrendCategory.fusion,
    TrendType.risk_escalation: TrendCategory.fusion,
    TrendType.narrative_divergence: TrendCategory.fusion,
    TrendType.market_uncertainty: TrendCategory.fusion,
    TrendType.market_reaction: TrendCategory.fusion,
    TrendType.market_underestimation: TrendCategory.meta,
    TrendType.market_overestimation: TrendCategory.meta,
    TrendType.recurring_volatility: TrendCategory.meta,
    TrendType.recurring_confidence_failure: TrendCategory.meta,
    TrendType.recurring_sharp_reversal: TrendCategory.meta,
    TrendType.strong_historical_alignment: TrendCategory.fusion,
    TrendType.structural_volatility: TrendCategory.fusion,
    TrendType.market_correction: TrendCategory.fusion,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


def severity_for(strength: float) -> Severity:
    """Deterministic strength → severity banding (Contract V1)."""
    if strength >= 0.85:
        return Severity.critical
    if strength >= 0.6:
        return Severity.high
    if strength >= 0.35:
        return Severity.medium
    return Severity.low


class Trend(BaseModel):
    """One detected trend — the structured event published downstream
    (Trend Contract V1).

    `strength` is the magnitude of the underlying movement in [0,1]
    (how big); `confidence` is how certain Atlas is the trend is real
    (how sure). They are deliberately separate: a huge move backed by
    one bookmaker is strong but uncertain; a small move corroborated
    across ten books is weak but certain. `severity` is the public
    banding of strength (low/medium/high/critical).

    `direction` is +1 / -1 / 0 from the HOME perspective where the
    concept is directional (market moves, momentum); 0 when not.

    `evidence` carries the numeric facts that justified the detection
    (emitted on the wire as `metrics`) — enough for any consumer to
    audit the trend without re-deriving it. `chart_data` carries
    render-ready series/points; `title` + `summary` are deterministic
    template renderings (atlas/trends/contract.py) — never LLM output.

    `agent` is the producing engine ("market" / "momentum" /
    "historical" / "impact" / "narrative").
    """

    model_config = ConfigDict(frozen=True)

    trend_id: UUID = Field(default_factory=uuid4)
    schema_version: str = TREND_SCHEMA_VERSION
    trend_type: TrendType
    category: TrendCategory
    agent: str = ""
    canonical_match_id: UUID
    competition_id: UUID | None = None
    minute: int | None = None
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    severity: Severity | None = None
    direction: int = Field(default=0, ge=-1, le=1)
    window_seconds: int | None = None
    title: str = ""
    summary: str = ""
    signals: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    chart_data: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=_utcnow)
    # ---- Contract V2 (Sprint 1.5) — evaluation results. Set by the
    # trend pipeline AFTER detection; None/empty means "not evaluated"
    # (a raw detector output that never went through the pipeline).
    publish_score: float | None = Field(default=None, ge=0.0, le=1.0)
    publication_tier: str | None = None
    lifecycle_state: str | None = None
    correlation_ids: list[str] = Field(default_factory=list)
    # ---- Contract V3 (Sprint 2) — interpretation + timeline + pattern.
    meaning: str | None = None
    meaning_category: str | None = None
    meaning_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    # Lifecycle timeline: {"instance_id", "previous_states": [...],
    # "observation_count"} — lets consumers see strengthening /
    # weakening / confirmed / failed without querying history.
    timeline: dict[str, Any] = Field(default_factory=dict)
    # Pattern memory: {"pattern_id", "occurrences",
    # "historical_success_rate"} when a recurrence is known.
    pattern: dict[str, Any] = Field(default_factory=dict)
    # ---- Contract V4 (Maturity Sprint 1.5) — historical intelligence.
    # What usually happens after this trend type (historical outcome
    # distribution): {"confirmed_rate", "failed_rate", "expired_rate",
    # "sample"} when enough history exists.
    historical_context: dict[str, Any] = Field(default_factory=dict)
    # Market memory profile for this trend type in scope:
    # {"occurrences", "confirmations", "failures", "expirations",
    # "avg_duration_seconds", "avg_confidence", "avg_strength"}.
    market_memory: dict[str, Any] = Field(default_factory=dict)
    # Competition intelligence snapshot: {"volatility", "confidence",
    # "fragmentation", "trend_density", ...}.
    competition_context: dict[str, Any] = Field(default_factory=dict)
    # Current competition regime classification (STABLE/VOLATILE/...).
    regime: str | None = None
    # Trend persistence profile: {"expected_duration_seconds",
    # "continuation_probability", "termination_probability", "sample"}.
    continuation: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        # Derive severity from strength when the caller didn't set it.
        # (frozen model: object.__setattr__ is the sanctioned escape.)
        if self.severity is None:
            object.__setattr__(self, "severity", severity_for(self.strength))

    def to_wire(self) -> dict[str, Any]:
        """JSON-safe Trend Contract V1 wire form for the trend stream."""
        return {
            "trend_id": str(self.trend_id),
            "schema_version": self.schema_version,
            "trend_type": self.trend_type.value,
            "category": self.category.value,
            "agent": self.agent,
            "confidence": self.confidence,
            "severity": self.severity.value if self.severity else None,
            "competition_id": str(self.competition_id) if self.competition_id else None,
            # Contract V1 `match_id` IS the canonical cross-provider id;
            # both keys are emitted so the meaning is unambiguous.
            "match_id": str(self.canonical_match_id),
            "canonical_match_id": str(self.canonical_match_id),
            "minute": self.minute,
            "strength": self.strength,
            "direction": self.direction,
            "window_seconds": self.window_seconds,
            "created_at": self.detected_at.isoformat(),
            "detected_at": self.detected_at.isoformat(),
            "title": self.title,
            "summary": self.summary,
            "signals": list(self.signals),
            "metrics": self.evidence,
            "chart_data": self.chart_data,
            # ---- v2 additions (every v1 key above is unchanged).
            "publish_score": self.publish_score,
            "publication_tier": self.publication_tier,
            "lifecycle_state": self.lifecycle_state,
            "correlation_ids": list(self.correlation_ids),
            # ---- v3 additions (every v1/v2 key above is unchanged).
            "meaning": self.meaning,
            "meaning_category": self.meaning_category,
            "meaning_confidence": self.meaning_confidence,
            "timeline": dict(self.timeline),
            "pattern": dict(self.pattern),
            # ---- v4 additions (every v1/v2/v3 key above is unchanged).
            "historical_context": dict(self.historical_context),
            "market_memory": dict(self.market_memory),
            "competition_context": dict(self.competition_context),
            "regime": self.regime,
            "continuation": dict(self.continuation),
        }


@dataclass(frozen=True, slots=True)
class TrendInputs:
    """Everything a detector may correlate over for one match tick.

    Every field except the id is optional — detectors are written to
    return [] when their inputs are absent, so the engine can run the
    full detector set against whatever data this event carried.

    `features` / `prior_features` are FeatureSnapshot.features dicts
    (sentiment_delta, signal_density, pressure_delta, …);
    `context` / `prior_context` are the recomputed match contexts from
    the context engine; `odds_history` is the persisted OddsTick
    timeline.
    """

    canonical_match_id: UUID
    competition_id: UUID | None = None
    minute: int | None = None
    context: dict[str, Any] | None = None
    prior_context: dict[str, Any] | None = None
    odds_context: dict[str, Any] | None = None
    odds_history: list[OddsTick] = dc_field(default_factory=list)
    signals: list[Signal] = dc_field(default_factory=list)
    impact_label: str | None = None
    impact_category: str | None = None
    features: dict[str, float] | None = None
    prior_features: dict[str, float] | None = None
    # Live match statistics when the event carried them (Sprint 1 —
    # MomentumTrendEngine input). Conventional keys, all optional:
    # possession_home/away, shots_home/away,
    # dangerous_attacks_home/away. Values are raw counts/percentages.
    match_stats: dict[str, float] | None = None
    # ATLAS-VECTOR-B / ATLAS-SIMILARITY-A: the shared SimilarityContext,
    # precomputed ASYNC by TrendIntelligencePipeline (SimilarityService) and
    # attached before the sync detectors run. `None` when no similarity
    # provider is configured or no query embedding could be built — consumers
    # then emit nothing (no degraded guess). Reusable by any engine, not just
    # the Oracle.
    similarity: "SimilarityContext | None" = None
