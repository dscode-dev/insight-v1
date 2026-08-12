"""Publication decision layer.

A signal is published only when BOTH gates pass:

    confidence >= min_confidence    AND    impact >= min_impact

Both thresholds are configurable. This suppresses noise (a single
yellow card, a tiny odds move) while letting strong intelligence
through (a red card, a critical goal context, a major probability
shift). Decision only — no posting.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import Counter
from pydantic import BaseModel, ConfigDict

from atlas.event_impact import Impact
from atlas.signal_engine import Signal

PUBLICATION_DECISIONS_TOTAL = Counter(
    "publication_decisions_total",
    "Publication decisions made by Atlas.",
    ["published", "signal_type"],
)


class PublishDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    publish: bool
    signal: Signal
    reason: str
    min_confidence: float
    min_impact: str


def _impact_of(label: str) -> Impact:
    try:
        return Impact[label]
    except KeyError:
        return Impact.LOW


class PublicationEngine:
    def __init__(
        self, *, min_confidence: float = 0.7, min_impact: Impact = Impact.HIGH
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0,1]")
        self._min_confidence = min_confidence
        self._min_impact = min_impact

    def decide(self, signal: Signal) -> PublishDecision:
        impact = _impact_of(signal.impact)
        conf_ok = signal.confidence >= self._min_confidence
        impact_ok = impact >= self._min_impact
        publish = conf_ok and impact_ok

        if publish:
            reason = "meets confidence + impact thresholds"
        elif not conf_ok and not impact_ok:
            reason = "below confidence and impact thresholds"
        elif not conf_ok:
            reason = "below confidence threshold"
        else:
            reason = "below impact threshold"

        PUBLICATION_DECISIONS_TOTAL.labels(
            published=str(publish).lower(), signal_type=signal.signal_type.value
        ).inc()
        return PublishDecision(
            publish=publish,
            signal=signal,
            reason=reason,
            min_confidence=self._min_confidence,
            min_impact=self._min_impact.label,
        )

    def decide_many(self, signals: list[Signal]) -> list[PublishDecision]:
        return [self.decide(s) for s in signals]

    def snapshot(self) -> dict[str, Any]:
        return {
            "min_confidence": self._min_confidence,
            "min_impact": self._min_impact.label,
        }
