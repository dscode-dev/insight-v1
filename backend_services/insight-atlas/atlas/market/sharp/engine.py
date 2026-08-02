"""Sharp Movement Detection — Magnus Absorption Part 6.

Identifies MEANINGFUL market behavior: fast, directional, coordinated
movement of the consensus view. Descriptive intelligence about how the
market is behaving — NOT betting advice and NOT an exploit signal.

  speed        = |latest consensus step| / FULL_SPEED_STEP
  persistence  = run of consecutive steps in the latest direction / 3
  coordination = share of bookmakers whose own fair home prob moved in
                 the latest consensus direction between the last two
                 snapshots they both priced

  sharp_movement_score = 0.45·speed + 0.25·persistence + 0.30·coordination

All components clamped to [0,1]; deterministic over the odds history.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.market.fair_probability import book_fair_probs, fair_prob_points
from atlas.odds.features import H2H
from atlas.odds.models import OddsTick

# One consensus step of this size saturates the speed component.
FULL_SPEED_STEP = 0.06
# Steps smaller than this don't count as directional movement.
DIRECTION_EPSILON = 0.002


@dataclass(frozen=True, slots=True)
class SharpMovementResult:
    score: float
    direction: int          # +1 toward home, -1 away from home, 0 flat
    speed: float
    persistence: float
    coordination: float
    coordinated_books: int
    total_books: int


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _book_home_steps(history: list[OddsTick]) -> dict[str, float]:
    """Per bookmaker: fair home prob change between its last two
    snapshots. Books with fewer than two snapshots are skipped."""
    h2h = sorted(
        (t for t in history if t.market == H2H), key=lambda t: t.captured_at
    )
    series: dict[str, list[float]] = {}
    for tick in h2h:
        fair = book_fair_probs(tick)
        if fair is not None and "home" in fair:
            series.setdefault(tick.bookmaker, []).append(fair["home"])
    return {
        book: values[-1] - values[-2]
        for book, values in series.items()
        if len(values) >= 2
    }


def sharp_movement(history: list[OddsTick]) -> SharpMovementResult | None:
    """Sharp-movement assessment of the latest consensus step. None
    with < 3 consensus points."""
    points = [v for _, v in fair_prob_points(history)]
    if len(points) < 3:
        return None
    deltas = [points[i] - points[i - 1] for i in range(1, len(points))]
    last = deltas[-1]
    if abs(last) < DIRECTION_EPSILON:
        direction = 0
        speed = 0.0
        persistence = 0.0
    else:
        direction = 1 if last > 0 else -1
        speed = _clamp(abs(last) / FULL_SPEED_STEP)
        run = 0
        for delta in reversed(deltas):
            if delta * direction > DIRECTION_EPSILON:
                run += 1
            else:
                break
        persistence = _clamp(run / 3.0)

    steps = _book_home_steps(history)
    coordinated = 0
    if direction != 0:
        coordinated = sum(
            1 for d in steps.values() if d * direction > DIRECTION_EPSILON
        )
    coordination = coordinated / len(steps) if steps else 0.0

    score = _clamp(0.45 * speed + 0.25 * persistence + 0.30 * coordination)
    return SharpMovementResult(
        score=round(score, 4),
        direction=direction,
        speed=round(speed, 4),
        persistence=round(persistence, 4),
        coordination=round(coordination, 4),
        coordinated_books=coordinated,
        total_books=len(steps),
    )
