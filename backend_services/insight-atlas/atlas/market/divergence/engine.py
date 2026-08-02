"""Divergence Engine — Magnus Absorption Part 3.

Measures significant DISAGREEMENT between bookmakers and identifies
outlier books. The complement of consensus, but spread-based (max-min)
so a single detached book registers loudly even when the rest agree.

  divergence_score 0.0 = books aligned
  divergence_score 1.0 = structurally split market

Outliers are books whose fair home probability deviates from the
cross-book MEDIAN by ≥ OUTLIER_DEVIATION.

Analytical description of market behavior only: no arbitrage math,
no margin exposure, no exploit guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlas.market.fair_probability import latest_fair_probs_by_book
from atlas.odds.models import OddsTick

# Mean per-outcome fair-prob spread at (or beyond) which the market is
# fully split.
FULL_SPLIT_SPREAD = 0.20
# Fair-prob deviation from the median that marks a book as an outlier.
OUTLIER_DEVIATION = 0.08


@dataclass(frozen=True, slots=True)
class DivergenceResult:
    score: float                       # 0 aligned … 1 split
    spread: float                      # mean per-outcome max-min spread
    outliers: list[str] = field(default_factory=list)
    bookmaker_count: int = 0


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def divergence(history: list[OddsTick]) -> DivergenceResult | None:
    """Cross-bookmaker disagreement at the latest snapshot. None when
    fewer than two books carry usable prices."""
    books = latest_fair_probs_by_book(history)
    if len(books) < 2:
        return None
    spreads: list[float] = []
    for outcome in ("home", "draw", "away"):
        values = [p[outcome] for p in books.values() if outcome in p]
        if len(values) >= 2:
            spreads.append(max(values) - min(values))
    if not spreads:
        return None
    spread = sum(spreads) / len(spreads)
    score = max(0.0, min(1.0, spread / FULL_SPLIT_SPREAD))

    home_probs = {b: p["home"] for b, p in books.items() if "home" in p}
    outliers: list[str] = []
    if len(home_probs) >= 3:
        median = _median(list(home_probs.values()))
        outliers = sorted(
            b for b, p in home_probs.items()
            if abs(p - median) >= OUTLIER_DEVIATION
        )
    return DivergenceResult(
        score=round(score, 4),
        spread=round(spread, 4),
        outliers=outliers,
        bookmaker_count=len(books),
    )
