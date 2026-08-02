"""Trend correlation domain — Sprint 1.5 Part 2.

Multiple trends occurring together are more important than isolated
trends. A CorrelationRule pairs compatible trend types inside a time
window on the same match; a hit produces a CorrelatedTrend record AND
a first-class fusion Trend (category=fusion) that flows through
scoring, persistence and publication like any other trend.

Pure deterministic logic. No ML. No LLM.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from atlas.trends.models import TrendType


class CorrelationType(str, enum.Enum):
    MARKET_CONVICTION = "MARKET_CONVICTION"
    IMMINENT_BREAKTHROUGH = "IMMINENT_BREAKTHROUGH"
    RISK_ESCALATION = "RISK_ESCALATION"
    NARRATIVE_DIVERGENCE = "NARRATIVE_DIVERGENCE"
    # Magnus Absorption (Sprint 1).
    MARKET_UNCERTAINTY = "MARKET_UNCERTAINTY"
    MARKET_REACTION = "MARKET_REACTION"
    # Intelligence Maturity (Sprint 1.5).
    STRONG_HISTORICAL_ALIGNMENT = "STRONG_HISTORICAL_ALIGNMENT"
    STRUCTURAL_VOLATILITY = "STRUCTURAL_VOLATILITY"
    MARKET_CORRECTION = "MARKET_CORRECTION"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CorrelatedTrend(BaseModel):
    """One correlation hit — the auditable record of which member
    trends co-occurred and the combined strength/confidence."""

    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    canonical_match_id: UUID
    correlation_type: CorrelationType
    member_trends: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    strength: float = Field(ge=0.0, le=1.0)
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class CorrelationRule:
    """Pair `members` of compatible trend types inside `window_seconds`
    on the same match. `require_direction_agreement` demands both
    members carry the same non-zero direction (e.g. a market moving the
    same way it is accelerating)."""

    correlation_type: CorrelationType
    members: tuple[TrendType, TrendType]
    fusion_type: TrendType
    window_seconds: int = 600
    require_direction_agreement: bool = False


DEFAULT_CORRELATION_RULES: tuple[CorrelationRule, ...] = (
    CorrelationRule(
        correlation_type=CorrelationType.MARKET_CONVICTION,
        members=(TrendType.market_shift, TrendType.market_acceleration),
        fusion_type=TrendType.market_conviction,
        require_direction_agreement=True,
    ),
    CorrelationRule(
        correlation_type=CorrelationType.IMMINENT_BREAKTHROUGH,
        members=(TrendType.pressure_building, TrendType.dominance_pattern),
        fusion_type=TrendType.imminent_breakthrough,
    ),
    CorrelationRule(
        correlation_type=CorrelationType.RISK_ESCALATION,
        members=(TrendType.risk_increase, TrendType.game_state_change),
        fusion_type=TrendType.risk_escalation,
    ),
    CorrelationRule(
        correlation_type=CorrelationType.NARRATIVE_DIVERGENCE,
        members=(TrendType.narrative_conflict, TrendType.market_shift),
        fusion_type=TrendType.narrative_divergence,
    ),
    # ---- Magnus Absorption (Sprint 1) — market-intelligence fusions.
    # Agreement strengthening while belief firms = conviction.
    CorrelationRule(
        correlation_type=CorrelationType.MARKET_CONVICTION,
        members=(
            TrendType.market_consensus_growing,
            TrendType.confidence_acceleration,
        ),
        fusion_type=TrendType.market_conviction,
    ),
    # A fragmented market that is also churning = uncertainty.
    CorrelationRule(
        correlation_type=CorrelationType.MARKET_UNCERTAINTY,
        members=(
            TrendType.market_fragmentation,
            TrendType.volatility_increase,
        ),
        fusion_type=TrendType.market_uncertainty,
    ),
    # A sharp repricing while pressure builds on the pitch = the market
    # reacting to match developments.
    CorrelationRule(
        correlation_type=CorrelationType.MARKET_REACTION,
        members=(
            TrendType.sharp_market_move,
            TrendType.pressure_building,
        ),
        fusion_type=TrendType.market_reaction,
    ),
    # ---- Intelligence Maturity (Sprint 1.5).
    # A sharp move on a team the market repeatedly underestimated =
    # the market correcting a recurring misprice.
    CorrelationRule(
        correlation_type=CorrelationType.MARKET_CORRECTION,
        members=(
            TrendType.market_underestimation,
            TrendType.sharp_market_move,
        ),
        fusion_type=TrendType.market_correction,
    ),
)


@dataclass(frozen=True, slots=True)
class EnrichedCorrelationRule:
    """Single-member rule over a V4-ENRICHED trend: the member type
    plus a deterministic predicate over the trend's historical /
    regime fields. Evaluated after enrichment (pipeline step 4b),
    where the standard two-member window rules can't see those fields
    yet. `evidence_of` extracts the public-safe facts the fusion
    trend's evidence carries."""

    correlation_type: CorrelationType
    member: TrendType
    fusion_type: TrendType
    predicate: "Callable[[Any], bool]"
    evidence_of: "Callable[[Any], dict[str, Any]]"
    window_seconds: int = 600


def _historical_alignment_predicate(trend: Any) -> bool:
    rate = (trend.historical_context or {}).get("confirmed_rate")
    return isinstance(rate, (int, float)) and rate > 0.7


def _historical_alignment_evidence(trend: Any) -> dict[str, Any]:
    h = trend.historical_context or {}
    return {
        "historical_confirmed_rate": h.get("confirmed_rate"),
        "historical_sample": h.get("sample"),
    }


def _structural_volatility_predicate(trend: Any) -> bool:
    return trend.regime == "VOLATILE"


def _structural_volatility_evidence(trend: Any) -> dict[str, Any]:
    return {"regime": trend.regime}


DEFAULT_ENRICHED_RULES: tuple[EnrichedCorrelationRule, ...] = (
    # Market conviction forming where history confirms > 70%.
    EnrichedCorrelationRule(
        correlation_type=CorrelationType.STRONG_HISTORICAL_ALIGNMENT,
        member=TrendType.market_conviction,
        fusion_type=TrendType.strong_historical_alignment,
        predicate=_historical_alignment_predicate,
        evidence_of=_historical_alignment_evidence,
    ),
    # Recurring volatility inside a VOLATILE competition regime.
    EnrichedCorrelationRule(
        correlation_type=CorrelationType.STRUCTURAL_VOLATILITY,
        member=TrendType.recurring_volatility,
        fusion_type=TrendType.structural_volatility,
        predicate=_structural_volatility_predicate,
        evidence_of=_structural_volatility_evidence,
    ),
)
