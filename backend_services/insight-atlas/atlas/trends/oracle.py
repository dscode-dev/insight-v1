"""Oracle — historical trend detectors.

V1 implements `historical_deviation`: the market has moved materially
away from where it OPENED, which is the strongest within-match
historical baseline available from data Atlas already persists (the
full odds timeline).

`historical_pattern` and `historical_similarity` are reserved in the
taxonomy: they require the historical similarity index
(atlas/models/similarity.py + the historical dataset) to be served
online, which is a model-registry promotion concern, not a detector
concern. They plug into the same TrendEngine via the same protocol
once that index is productionised — see ATLAS_READINESS_REPORT.md §10.
"""

from __future__ import annotations

from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType
from atlas.trends.ninja import _chart, _consensus_prob_points


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


class HistoricalDeviationDetector:
    """Current consensus implied probability deviates from the OPENING
    consensus by ≥ threshold — the match has drifted materially from
    its pre-match baseline."""

    def __init__(self, *, min_prob_deviation: float = 0.07, min_samples: int = 3) -> None:
        self._min_dev = min_prob_deviation
        self._min_samples = min_samples

    def detect(self, inputs: TrendInputs) -> list[Trend]:
        points = _consensus_prob_points(inputs)
        probs = [v for _, v in points]
        if len(probs) < self._min_samples:
            return []
        opening, current = probs[0], probs[-1]
        deviation = current - opening
        if abs(deviation) < self._min_dev:
            return []
        return [
            Trend(
                trend_type=TrendType.historical_deviation,
                category=TrendCategory.oracle,
                canonical_match_id=inputs.canonical_match_id,
                competition_id=inputs.competition_id,
                minute=inputs.minute,
                strength=_clamp(abs(deviation) / 0.25),
                confidence=_clamp(0.55 + 0.03 * len(probs)),
                direction=1 if deviation > 0 else -1,
                evidence={
                    "opening_prob": round(opening, 4),
                    "current_prob": round(current, 4),
                    "deviation": round(deviation, 4),
                    "snapshots": len(probs),
                },
                chart_data=_chart(points),
            )
        ]
