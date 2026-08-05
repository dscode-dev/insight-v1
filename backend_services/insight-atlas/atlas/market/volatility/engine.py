"""Volatility Engine — Magnus Absorption Part 5.

Measures how RESTLESS the market is over the observed window:

  movement frequency = fraction of consecutive consensus fair-prob
                       steps with |Δ| ≥ MOVE_EPSILON
  movement magnitude = Σ |Δ| over the window, saturating at
                       FULL_MAGNITUDE
  volatility_score   = 0.5 · frequency + 0.5 · magnitude(normalised)
  stability          = longest quiet run / total steps (evidence only)

Deterministic over the odds history.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.market.fair_probability import fair_prob_points
from atlas.odds.models import OddsTick

# A consensus step below this is "quiet".
MOVE_EPSILON = 0.005
# Total absolute movement at which the magnitude component saturates.
FULL_MAGNITUDE = 0.12


@dataclass(frozen=True, slots=True)
class VolatilityResult:
    score: float        # 0 still … 1 churning
    frequency: float    # fraction of moving steps
    magnitude: float    # Σ|Δ| (uncapped, for evidence)
    stability: float    # longest quiet run / steps


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def volatility(
    history: list[OddsTick], *, points: list[float] | None = None,
) -> VolatilityResult | None:
    """Market restlessness over the window. None with < 3 consensus
    points (no movement to measure).

    `points` lets a caller that already computed
    `fair_prob_points(history)` (an O(n) scan over the timeline —
    `MarketStateEngine` otherwise redoes it once here and again in
    `sharp_movement`) pass the values straight through.
    """
    points = points if points is not None else [v for _, v in fair_prob_points(history)]
    if len(points) < 3:
        return None
    deltas = [points[i] - points[i - 1] for i in range(1, len(points))]
    moving = [abs(d) >= MOVE_EPSILON for d in deltas]
    frequency = sum(moving) / len(deltas)
    magnitude = sum(abs(d) for d in deltas)

    longest_quiet = 0
    run = 0
    for is_moving in moving:
        run = 0 if is_moving else run + 1
        longest_quiet = max(longest_quiet, run)
    stability = longest_quiet / len(deltas)

    score = _clamp(0.5 * frequency + 0.5 * _clamp(magnitude / FULL_MAGNITUDE))
    return VolatilityResult(
        score=round(score, 4),
        frequency=round(frequency, 4),
        magnitude=round(magnitude, 4),
        stability=round(stability, 4),
    )
