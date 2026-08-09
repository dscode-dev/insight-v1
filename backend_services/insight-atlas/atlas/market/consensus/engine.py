"""Consensus Engine — Magnus Absorption Part 2.

Measures how strongly the bookmakers AGREE about the match: low
cross-book dispersion of fair probabilities = a unified market view.

  consensus_score 0.0 = fragmented market (books far apart)
  consensus_score 1.0 = strong market agreement

Deterministic: dispersion is the MAX per-outcome population standard
deviation of fair probabilities across books (the most-disputed
outcome defines how fragmented the market is), mapped linearly onto
[0, 1] with FULL_DISAGREEMENT_STD as the zero point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from atlas.market.fair_probability import latest_fair_probs_by_book
from atlas.odds.models import OddsTick

# Per-outcome stddev at (or beyond) which the market counts as fully
# fragmented. 8 probability points of cross-book disagreement on one
# outcome is an extreme, structurally split market.
FULL_DISAGREEMENT_STD = 0.08


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    score: float            # 0 fragmented … 1 strong agreement
    dispersion: float       # max per-outcome stddev of fair probs
    bookmaker_count: int


def _std(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def consensus(
    history: list[OddsTick], *, books: dict[str, dict[str, float]] | None = None,
) -> ConsensusResult | None:
    """Cross-bookmaker agreement at the latest snapshot. None when
    fewer than two books carry usable prices.

    `books` — see `fair_probabilities`'s docstring; same reuse seam.
    """
    books = books if books is not None else latest_fair_probs_by_book(history)
    if len(books) < 2:
        return None
    stds: list[float] = []
    for outcome in ("home", "draw", "away"):
        values = [p[outcome] for p in books.values() if outcome in p]
        if len(values) >= 2:
            stds.append(_std(values))
    if not stds:
        return None
    dispersion = max(stds)
    score = max(0.0, min(1.0, 1.0 - dispersion / FULL_DISAGREEMENT_STD))
    return ConsensusResult(
        score=round(score, 4),
        dispersion=round(dispersion, 4),
        bookmaker_count=len(books),
    )
