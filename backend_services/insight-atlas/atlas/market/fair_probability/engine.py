"""Fair Probability Engine — Magnus Absorption Part 1.

Extracts implied probabilities from bookmaker odds and produces the
market's FAIR (margin-free) probability view:

  implied(price)        = 1 / price
  book fair probs       = implied / Σ implied over the book's outcomes
                          (the per-book normalisation removes the
                          bookmaker margin INTERNALLY — the margin
                          itself is never returned, stored or emitted)
  consensus fair probs  = per-outcome MEDIAN across bookmakers,
                          re-normalised to sum to 1

Median, not mean: one detached bookmaker must not drag the market's
fair view (same posture as the anomaly detector).

Deterministic + reproducible: the same odds history always produces
the same probabilities. Pure functions, no I/O, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from atlas.odds.features import H2H, _latest_per_bookmaker
from atlas.odds.models import OddsTick

OUTCOMES = ("home", "draw", "away")


@dataclass(frozen=True, slots=True)
class FairProbabilities:
    """The market's margin-free probability view at the latest snapshot."""

    home: float
    draw: float
    away: float
    bookmaker_count: int

    def as_dict(self) -> dict[str, float]:
        return {
            "home": round(self.home, 4),
            "draw": round(self.draw, 4),
            "away": round(self.away, 4),
        }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def book_fair_probs(tick: OddsTick) -> dict[str, float] | None:
    """One bookmaker's margin-free outcome probabilities. None when the
    tick doesn't carry at least two priceable outcomes."""
    inverse: dict[str, float] = {}
    for outcome in OUTCOMES:
        price = getattr(tick, outcome)
        if price is not None and price > 0:
            inverse[outcome] = 1.0 / price
    if len(inverse) < 2:
        return None
    total = sum(inverse.values())  # internal normaliser only — never exposed
    return {o: v / total for o, v in inverse.items()}


def latest_fair_probs_by_book(
    history: list[OddsTick],
) -> dict[str, dict[str, float]]:
    """bookmaker → fair probs at that book's latest h2h snapshot."""
    h2h = [t for t in history if t.market == H2H]
    out: dict[str, dict[str, float]] = {}
    for tick in _latest_per_bookmaker(h2h):
        fair = book_fair_probs(tick)
        if fair is not None:
            out[tick.bookmaker] = fair
    return out


def fair_probabilities(
    history: list[OddsTick], *, books: dict[str, dict[str, float]] | None = None,
) -> FairProbabilities | None:
    """Market consensus fair probabilities (median across books,
    re-normalised). None when no bookmaker carries usable prices.

    `books` lets a caller that already computed
    `latest_fair_probs_by_book(history)` (e.g. `MarketStateEngine`,
    which otherwise recomputes this O(n) scan up to 4x per `compute()`
    call) pass it straight through instead of redoing the work.
    Standalone callers omit it and get the original behavior.
    """
    books = books if books is not None else latest_fair_probs_by_book(history)
    if not books:
        return None
    medians: dict[str, float] = {}
    for outcome in OUTCOMES:
        values = [probs[outcome] for probs in books.values() if outcome in probs]
        if values:
            medians[outcome] = _median(values)
    total = sum(medians.values())
    if total <= 0:
        return None
    return FairProbabilities(
        home=medians.get("home", 0.0) / total,
        draw=medians.get("draw", 0.0) / total,
        away=medians.get("away", 0.0) / total,
        bookmaker_count=len(books),
    )


def fair_prob_points(
    history: list[OddsTick], *, outcome: str = "home"
) -> list[tuple[datetime, float]]:
    """Timestamped consensus fair-probability series for one outcome:
    per snapshot instant, forward-fill each book's latest fair prob and
    take the cross-book median."""
    h2h = sorted(
        (t for t in history if t.market == H2H), key=lambda t: t.captured_at
    )
    timestamps = sorted({t.captured_at for t in h2h})
    latest_by_book: dict[str, float] = {}
    points: list[tuple[datetime, float]] = []
    for ts in timestamps:
        for tick in h2h:
            if tick.captured_at != ts:
                continue
            fair = book_fair_probs(tick)
            if fair is not None and outcome in fair:
                latest_by_book[tick.bookmaker] = fair[outcome]
        if latest_by_book:
            points.append((ts, _median(list(latest_by_book.values()))))
    return points
