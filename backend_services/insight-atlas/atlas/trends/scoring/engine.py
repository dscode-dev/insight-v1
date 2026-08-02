"""Publish Score Engine — deterministic publication-worthiness scoring.

Every factor contribution is recorded in PublishScore.factors and the
human-readable reasoning string, so any score is auditable and exactly
reproducible from the trend + its lifecycle/correlation context.

Score → tier (Sprint 1.5 spec):

    [0.00, 0.30)  SUPPRESS          persist only
    [0.30, 0.60)  STORE_ONLY        persist only
    [0.60, 0.80)  PUBLISH           persist + stream
    [0.80, 1.00]  PRIORITY_PUBLISH  persist + stream, priority flag
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict, Field

from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.models import Severity, Trend, TrendType

PUBLISH_SCORE_TOTAL = Counter(
    "publish_score_total",
    "Publication tier decisions.",
    ["tier"],
)
PRIORITY_TRENDS_TOTAL = Counter(
    "priority_trends_total",
    "Trends published with the priority flag.",
)


class PublicationTier(str, enum.Enum):
    SUPPRESS = "suppress"
    STORE_ONLY = "store_only"
    PUBLISH = "publish"
    PRIORITY_PUBLISH = "priority_publish"

    @property
    def streams(self) -> bool:
        return self in (PublicationTier.PUBLISH, PublicationTier.PRIORITY_PUBLISH)

    @property
    def metric_label(self) -> str:
        return {
            PublicationTier.SUPPRESS: "suppressed",
            PublicationTier.STORE_ONLY: "stored",
            PublicationTier.PUBLISH: "published",
            PublicationTier.PRIORITY_PUBLISH: "priority",
        }[self]


def tier_for(score: float) -> PublicationTier:
    if score < 0.30:
        return PublicationTier.SUPPRESS
    if score < 0.60:
        return PublicationTier.STORE_ONLY
    if score < 0.80:
        return PublicationTier.PUBLISH
    return PublicationTier.PRIORITY_PUBLISH


class PublishScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    tier: PublicationTier
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    factors: dict[str, float]


# Per-state lifecycle adjustments: confirmed/strengthening trends are
# worth more; weakening/failed/expired ones are not news.
_LIFECYCLE_FACTOR: dict[TrendLifecycleState, float] = {
    TrendLifecycleState.CONFIRMED: 0.15,
    TrendLifecycleState.STRENGTHENING: 0.10,
    TrendLifecycleState.ACTIVE: 0.0,
    TrendLifecycleState.WEAKENING: -0.10,
    TrendLifecycleState.FAILED: -0.30,
    TrendLifecycleState.EXPIRED: -0.30,
}

_SEVERITY_FACTOR: dict[Severity, float] = {
    Severity.critical: 0.10,
    Severity.high: 0.05,
    Severity.medium: 0.0,
    Severity.low: -0.05,
}

# Historical importance: trend types that experience shows matter more
# to consumers. Configurable via the constructor.
DEFAULT_TYPE_IMPORTANCE: dict[TrendType, float] = {
    TrendType.impact_assessment: 0.05,
    TrendType.market_anomaly: 0.05,
    TrendType.market_conviction: 0.05,
    TrendType.imminent_breakthrough: 0.05,
    TrendType.risk_escalation: 0.05,
    TrendType.historical_deviation: 0.03,
    TrendType.sharp_market_move: 0.05,
    TrendType.market_fragmentation: 0.03,
    TrendType.market_uncertainty: 0.05,
    TrendType.market_reaction: 0.05,
    TrendType.market_underestimation: 0.05,
    TrendType.market_overestimation: 0.05,
    TrendType.strong_historical_alignment: 0.05,
    TrendType.market_correction: 0.05,
    TrendType.structural_volatility: 0.03,
}


class PublishScoreEngine:
    def __init__(
        self,
        *,
        strength_weight: float = 0.35,
        confidence_weight: float = 0.35,
        correlation_bonus: float = 0.10,
        impact_bonus: float = 0.05,
        signal_bonus_per: float = 0.02,
        signal_bonus_cap: int = 3,
        stale_age_seconds: int = 1800,
        stale_penalty: float = -0.05,
        type_importance: dict[TrendType, float] | None = None,
    ) -> None:
        self._w_strength = strength_weight
        self._w_confidence = confidence_weight
        self._corr_bonus = correlation_bonus
        self._impact_bonus = impact_bonus
        self._sig_per = signal_bonus_per
        self._sig_cap = signal_bonus_cap
        self._stale_age = stale_age_seconds
        self._stale_penalty = stale_penalty
        self._importance = (
            dict(type_importance)
            if type_importance is not None
            else dict(DEFAULT_TYPE_IMPORTANCE)
        )

    def score(
        self,
        trend: Trend,
        *,
        lifecycle_state: TrendLifecycleState | None = None,
        instance: TrendInstance | None = None,
        correlated: bool = False,
        impact_label: str | None = None,
        now: datetime | None = None,
    ) -> PublishScore:
        ts = now or datetime.now(timezone.utc)
        factors: dict[str, float] = {}

        factors["strength"] = round(self._w_strength * trend.strength, 4)
        factors["confidence"] = round(self._w_confidence * trend.confidence, 4)
        if trend.severity is not None:
            factors["severity"] = _SEVERITY_FACTOR.get(trend.severity, 0.0)
        if lifecycle_state is not None:
            factors["lifecycle"] = _LIFECYCLE_FACTOR.get(lifecycle_state, 0.0)
        if correlated or trend.correlation_ids:
            factors["correlation"] = self._corr_bonus
        if impact_label == "CRITICAL":
            factors["impact"] = self._impact_bonus
        if trend.signals:
            factors["signals"] = round(
                self._sig_per * min(len(trend.signals), self._sig_cap), 4
            )
        importance = self._importance.get(trend.trend_type, 0.0)
        if importance:
            factors["historical_importance"] = importance
        # Trend age: an old, never-confirmed instance is stale news.
        if (
            instance is not None
            and lifecycle_state is not None
            and not lifecycle_state.terminal
            and (ts - instance.created_at).total_seconds() > self._stale_age
        ):
            factors["age"] = self._stale_penalty

        raw = sum(factors.values())
        final = max(0.0, min(1.0, round(raw, 4)))
        tier = tier_for(final)
        PUBLISH_SCORE_TOTAL.labels(tier=tier.metric_label).inc()

        reasoning = "; ".join(
            f"{name}={value:+.3f}" for name, value in factors.items()
        ) + f" => score={final:.3f} tier={tier.value}"
        return PublishScore(
            score=final,
            tier=tier,
            confidence=trend.confidence,
            reasoning=reasoning,
            factors=factors,
        )
