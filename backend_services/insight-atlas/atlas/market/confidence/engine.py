"""Market Confidence Engine — Magnus Absorption Part 4.

Measures how DECISIVE the market's belief is and how that belief is
evolving:

  market_confidence  = 0.7 · decisiveness + 0.3 · consensus
      decisiveness   = (p1 − p2) / 0.5 clamped to [0,1], where p1/p2
                       are the top-two consensus fair probabilities —
                       a market split 34/33/33 believes nothing
                       (≈0); a market at 75/15/10 believes hard (≈1).
      consensus      = cross-book agreement (atlas/market/consensus)
  confidence_velocity = decisiveness now − decisiveness at the
                       midpoint of the observed series (positive =
                       belief firming, negative = belief decaying).

Deterministic over the odds history; reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.market.consensus import consensus
from atlas.market.fair_probability import (
    FairProbabilities,
    book_fair_probs,
    fair_probabilities,
)
from atlas.odds.features import H2H
from atlas.odds.models import OddsTick

# (p1 - p2) gap at which decisiveness saturates.
FULL_DECISIVENESS_GAP = 0.5


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    score: float       # 0 undecided … 1 decisive + unified
    velocity: float    # decisiveness change over the recent half-window
    decisiveness: float


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _decisiveness(probs: dict[str, float]) -> float | None:
    values = sorted(probs.values(), reverse=True)
    if len(values) < 2:
        return None
    return _clamp((values[0] - values[1]) / FULL_DECISIVENESS_GAP)


def _decisiveness_points(history: list[OddsTick]) -> list[float]:
    """Per-snapshot decisiveness series (forward-filled book fair
    probs, cross-book median per outcome)."""
    h2h = sorted(
        (t for t in history if t.market == H2H), key=lambda t: t.captured_at
    )
    timestamps = sorted({t.captured_at for t in h2h})
    latest_by_book: dict[str, dict[str, float]] = {}
    series: list[float] = []
    for ts in timestamps:
        for tick in h2h:
            if tick.captured_at != ts:
                continue
            fair = book_fair_probs(tick)
            if fair is not None:
                latest_by_book[tick.bookmaker] = fair
        if not latest_by_book:
            continue
        medians: dict[str, float] = {}
        for outcome in ("home", "draw", "away"):
            values = [
                p[outcome] for p in latest_by_book.values() if outcome in p
            ]
            if values:
                ordered = sorted(values)
                n = len(ordered)
                medians[outcome] = (
                    ordered[n // 2]
                    if n % 2 == 1
                    else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
                )
        d = _decisiveness(medians)
        if d is not None:
            series.append(d)
    return series


def market_confidence(
    history: list[OddsTick],
    *,
    books: dict[str, dict[str, float]] | None = None,
    fair: FairProbabilities | None = None,
) -> ConfidenceResult | None:
    """Confidence + velocity over the odds history. None when the
    market view can't be computed.

    `books`/`fair` let a caller that already computed
    `latest_fair_probs_by_book(history)`/`fair_probabilities(history)`
    (`MarketStateEngine`) pass them straight through instead of
    recomputing — same reuse seam as `consensus`/`divergence`.
    """
    fair = fair if fair is not None else fair_probabilities(history, books=books)
    if fair is None:
        return None
    decisiveness = _decisiveness(fair.as_dict())
    if decisiveness is None:
        return None
    agreement = consensus(history, books=books)
    consensus_part = agreement.score if agreement is not None else 0.5
    score = _clamp(0.7 * decisiveness + 0.3 * consensus_part)

    series = _decisiveness_points(history)
    velocity = 0.0
    if len(series) >= 2:
        midpoint = series[len(series) // 2] if len(series) >= 3 else series[0]
        velocity = series[-1] - midpoint
    return ConfidenceResult(
        score=round(score, 4),
        velocity=round(velocity, 4),
        decisiveness=round(decisiveness, 4),
    )
