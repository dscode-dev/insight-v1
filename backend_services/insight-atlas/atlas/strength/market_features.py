"""Market-microstructure signals for the live similarity engine.

Thin adapter over Atlas's EXISTING market-intelligence engines
(`atlas/market/`) — no new odds math. `MarketStateEngine` already turns
an `OddsTick` history into margin-free fair probabilities, consensus,
divergence, volatility and sharp-movement; this module just reads the
two similarity-engine signals (`market_pressure`, `line_movement`) plus
`market_entropy` (used the same way the orchestrator's original
hand-rolled volatility fallback already did) out of that existing
result — a first-class, live-populated table (`atlas.odds_ticks`), not
a new ingestion path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from atlas.market.fair_probability import fair_prob_points
from atlas.market.state import MarketState, MarketStateEngine
from atlas.odds.models import OddsTick
from atlas.strength.formulas import line_movement as _line_movement_delta


@dataclass(frozen=True, slots=True)
class MarketFeatures:
    """None fields mean "no usable odds for this match" — callers must
    omit the signal, never substitute a fabricated neutral value (same
    missing-data discipline the rest of the similarity engine follows).
    """

    market_pressure: float | None  # unit [0, 1] — the market's favorite strength
    market_entropy: float | None  # unit [0, 1] — 0 = certain, 1 = maximally uncertain
    line_movement: float | None  # signed [-1, 1] — closing minus opening home prob
    market_available: bool


def market_features_for_match(history: list[OddsTick]) -> MarketFeatures:
    state = MarketStateEngine(observe_metrics=False).compute(history)
    if state.fair is None:
        return MarketFeatures(
            market_pressure=None, market_entropy=None, line_movement=None,
            market_available=False,
        )
    return MarketFeatures(
        market_pressure=_favorite_strength(state),
        market_entropy=_entropy(state),
        line_movement=_movement(history),
        market_available=True,
    )


def _favorite_strength(state: MarketState) -> float:
    assert state.fair is not None
    return max(state.fair.home, state.fair.draw, state.fair.away)


def _entropy(state: MarketState) -> float:
    assert state.fair is not None
    probabilities = (state.fair.home, state.fair.draw, state.fair.away)
    raw = -sum(p * math.log(p + 1e-12) for p in probabilities)
    return max(0.0, min(1.0, raw / math.log(3)))


def _movement(history: list[OddsTick]) -> float | None:
    points = fair_prob_points(history, outcome="home")
    if len(points) < 2:
        return None
    _, opening = points[0]
    _, closing = points[-1]
    return _line_movement_delta(opening, closing)
