"""Sentinel — impact / risk trend detectors.

Operate on the Event Impact Engine's classification plus the match
context transitions the Context Recalculation Engine produces.

  impact_assessment  — a HIGH/CRITICAL event landed: structured impact view
  game_state_change  — the match moved between game states
  risk_increase      — pressure rising late in a tight game state
"""

from __future__ import annotations

from typing import Any

from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType

_IMPACT_STRENGTH = {"LOW": 0.2, "MEDIUM": 0.45, "HIGH": 0.7, "CRITICAL": 0.95}


def _f(d: dict[str, Any] | None, key: str) -> float | None:
    if not d:
        return None
    try:
        return float(d.get(key))
    except (TypeError, ValueError):
        return None


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class ImpactAssessmentDetector:
    """Emit a structured impact trend for HIGH/CRITICAL events. LOW and
    MEDIUM stay silent — they are signal-engine territory, not trends."""

    def __init__(self, *, min_impact: str = "HIGH") -> None:
        self._min_strength = _IMPACT_STRENGTH.get(min_impact, 0.7)

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        if not inputs.impact_label:
            return []
        strength = _IMPACT_STRENGTH.get(inputs.impact_label)
        if strength is None or strength < self._min_strength:
            return []
        return [
            Trend(
                trend_type=TrendType.impact_assessment,
                category=TrendCategory.sentinel,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=strength,
                confidence=0.85,
                direction=0,
                evidence={
                    "impact": inputs.impact_label,
                    "category": inputs.impact_category,
                    "signals": [s.signal_type.value for s in inputs.signals],
                },
            )
        ]


class GameStateChangeDetector:
    """The recomputed context's game_state differs from the prior one
    (pre_match → early → first_half → … → stoppage)."""

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        now = (inputs.context or {}).get("game_state")
        prev = (inputs.prior_context or {}).get("game_state")
        if not now or not prev or now == prev:
            return []
        return [
            Trend(
                trend_type=TrendType.game_state_change,
                category=TrendCategory.sentinel,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=0.5,
                confidence=0.9,
                direction=0,
                evidence={"from": prev, "to": now},
            )
        ]


class RiskIncreaseDetector:
    """Pressure is high AND rising while the game is late and the
    market is tight — conditions where the next event is most likely
    to flip the match narrative."""

    def __init__(
        self,
        *,
        min_pressure: float = 0.6,
        min_rise: float = 0.05,
        min_minute: int = 60,
        max_prob_gap: float = 0.3,
    ) -> None:
        self._min_pressure = min_pressure
        self._min_rise = min_rise
        self._min_minute = min_minute
        self._max_gap = max_prob_gap

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        if inputs.minute is None or inputs.minute < self._min_minute:
            return []
        now = _f(inputs.context, "pressure")
        prev = _f(inputs.prior_context, "pressure")
        if now is None or prev is None:
            return []
        rise = now - prev
        if now < self._min_pressure or rise < self._min_rise:
            return []
        probs = (inputs.context or {}).get("contextual_probabilities") or {}
        tight = True
        gap = None
        values = [v for v in probs.values() if isinstance(v, (int, float))]
        if len(values) >= 2:
            gap = max(values) - min(values)
            tight = gap <= self._max_gap
        if not tight:
            return []
        lateness = min(inputs.minute / 90.0, 1.2)
        return [
            Trend(
                trend_type=TrendType.risk_increase,
                category=TrendCategory.sentinel,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(now * lateness),
                confidence=_clamp(0.55 + rise + 0.1 * (1 if gap is not None else 0)),
                direction=0,
                evidence={
                    "pressure_prev": round(prev, 4),
                    "pressure_now": round(now, 4),
                    "rise": round(rise, 4),
                    "minute": inputs.minute,
                    "prob_gap": round(gap, 4) if gap is not None else None,
                },
            )
        ]
