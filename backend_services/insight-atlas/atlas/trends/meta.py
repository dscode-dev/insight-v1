"""Meta trend detector — Intelligence Maturity Part 3 (detection side).

Reads the `intelligence_state.meta` aggregates the MetaTrendEngine
computed (and the IntelligenceWatcher scheduled) and emits META trends
when recurrence crosses the configurable thresholds. Pure function of
the context dict: the engine owns the queries, this detector owns the
thresholds — deterministic and minimum-sample-gated.

META trends are cross-match intelligence anchored on the scope's most
recent match (the Trend contract is match-keyed); the scope itself is
in the evidence.
"""

from __future__ import annotations

from typing import Any

from atlas.intelligence.meta_trends.engine import META_TRENDS_TOTAL
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class MetaTrendDetector:
    """Recurrence thresholds over the meta scan. All knobs explicit
    (Part 3: minimum sample size configurable)."""

    def __init__(
        self,
        *,
        min_sample: int = 3,
        estimation_rate: float = 0.7,
        volatility_min_closures: int = 3,
        volatility_min_matches: int = 2,
        failure_rate: float = 0.6,
        reversal_rate: float = 0.5,
    ) -> None:
        self._min_sample = min_sample
        self._estimation_rate = estimation_rate
        self._vol_closures = volatility_min_closures
        self._vol_matches = volatility_min_matches
        self._failure_rate = failure_rate
        self._reversal_rate = reversal_rate

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        state = (inputs.context or {}).get("intelligence_state") or {}
        meta = state.get("meta") if isinstance(state, dict) else None
        if not isinstance(meta, dict):
            return []
        scope = str(meta.get("scope", ""))
        out: list[Trend] = []

        def emit(trend_type: TrendType, *, strength: float,
                 confidence: float, evidence: dict[str, Any]) -> None:
            out.append(Trend(
                trend_type=trend_type,
                category=TrendCategory.meta,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                strength=_clamp(strength),
                confidence=_clamp(confidence),
                direction=0,
                evidence={"scope": scope, **evidence},
            ))
            META_TRENDS_TOTAL.labels(trend_type=trend_type.value).inc()

        # Market under/overestimation per team: the market repeatedly
        # repriced toward (under) / against (over) the team AND those
        # repricings kept confirming.
        for team in meta.get("teams") or []:
            name = str(team.get("team", ""))
            if not name:
                continue
            toward_samples = int(team.get("toward_samples", 0))
            toward_rate = float(team.get("toward_rate", 0.0))
            if (
                toward_samples >= self._min_sample
                and toward_rate >= self._estimation_rate
            ):
                emit(
                    TrendType.market_underestimation,
                    strength=_clamp(toward_rate),
                    confidence=_clamp(0.4 + 0.1 * toward_samples),
                    evidence={"team": name, "samples": toward_samples,
                              "confirmed_rate": round(toward_rate, 4)},
                )
            against_samples = int(team.get("against_samples", 0))
            against_rate = float(team.get("against_rate", 0.0))
            if (
                against_samples >= self._min_sample
                and against_rate >= self._estimation_rate
            ):
                emit(
                    TrendType.market_overestimation,
                    strength=_clamp(against_rate),
                    confidence=_clamp(0.4 + 0.1 * against_samples),
                    evidence={"team": name, "samples": against_samples,
                              "confirmed_rate": round(against_rate, 4)},
                )

        # Recurring volatility across matches in the scope.
        closures = int(meta.get("volatility_closures", 0))
        matches = int(meta.get("volatility_matches", 0))
        if closures >= self._vol_closures and matches >= self._vol_matches:
            emit(
                TrendType.recurring_volatility,
                strength=_clamp(closures / (3.0 * self._vol_closures)),
                confidence=_clamp(0.4 + 0.1 * matches),
                evidence={"closures": closures, "matches": matches},
            )

        # Repeated confidence failures.
        conf_samples = int(meta.get("confidence_samples", 0))
        conf_failures = int(meta.get("confidence_failures", 0))
        if (
            conf_samples >= self._min_sample
            and conf_failures / conf_samples >= self._failure_rate
        ):
            emit(
                TrendType.recurring_confidence_failure,
                strength=_clamp(conf_failures / conf_samples),
                confidence=_clamp(0.4 + 0.1 * conf_samples),
                evidence={"failures": conf_failures, "samples": conf_samples,
                          "failure_rate": round(conf_failures / conf_samples, 4)},
            )

        # Repeated sharp reversals.
        sharp_samples = int(meta.get("sharp_samples", 0))
        sharp_reversals = int(meta.get("sharp_reversals", 0))
        if (
            sharp_samples >= self._min_sample
            and sharp_reversals / sharp_samples >= self._reversal_rate
        ):
            emit(
                TrendType.recurring_sharp_reversal,
                strength=_clamp(sharp_reversals / sharp_samples),
                confidence=_clamp(0.4 + 0.1 * sharp_samples),
                evidence={"reversals": sharp_reversals,
                          "samples": sharp_samples,
                          "reversal_rate": round(sharp_reversals / sharp_samples, 4)},
            )
        return out
