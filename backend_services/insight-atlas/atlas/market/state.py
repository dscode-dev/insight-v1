"""Market State — the composed market-intelligence view (Part 7 input).

One deterministic pass over a match's odds history produces the
`market_state` dict carried in the match context, available to the
trend engine, lifecycle, correlation, watchers and (via trend
evidence) Nexus.

PUBLIC-SAFE BY CONSTRUCTION: only market confidence, consensus,
divergence, volatility, fair probabilities and sharp-movement scores
appear here. Bookmaker margins/overrounds exist transiently inside the
fair-probability normalisation and are never emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter, Histogram

from atlas.market.confidence import ConfidenceResult, market_confidence
from atlas.market.consensus import ConsensusResult, consensus
from atlas.market.divergence import DivergenceResult, divergence
from atlas.market.fair_probability import (
    FairProbabilities,
    fair_prob_points,
    fair_probabilities,
    latest_fair_probs_by_book,
)
from atlas.market.sharp import SharpMovementResult, sharp_movement
from atlas.market.volatility import VolatilityResult, volatility
from atlas.odds.models import OddsTick

_SCORE_BUCKETS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)

MARKET_CONSENSUS_SCORE = Histogram(
    "market_consensus_score",
    "Cross-bookmaker agreement per market-state computation.",
    buckets=_SCORE_BUCKETS,
)
MARKET_DIVERGENCE_SCORE = Histogram(
    "market_divergence_score",
    "Cross-bookmaker disagreement per market-state computation.",
    buckets=_SCORE_BUCKETS,
)
MARKET_CONFIDENCE_SCORE = Histogram(
    "market_confidence_score",
    "Market decisiveness per market-state computation.",
    buckets=_SCORE_BUCKETS,
)
MARKET_VOLATILITY_SCORE = Histogram(
    "market_volatility_score",
    "Market restlessness per market-state computation.",
    buckets=_SCORE_BUCKETS,
)
MARKET_SHARP_MOVEMENTS_TOTAL = Counter(
    "market_sharp_movements_total",
    "Sharp market movements observed (score >= the sharp threshold).",
)

# Score at which a movement counts as sharp for the counter metric —
# mirrors the SharpMarketMoveDetector default.
SHARP_COUNTER_THRESHOLD = 0.6


@dataclass(frozen=True, slots=True)
class MarketState:
    fair: FairProbabilities | None
    consensus: ConsensusResult | None
    divergence: DivergenceResult | None
    confidence: ConfidenceResult | None
    volatility: VolatilityResult | None
    sharp: SharpMovementResult | None
    snapshots: int

    def as_dict(self) -> dict[str, Any]:
        """The `market_state` context entry. Stable keys; absent
        engines contribute None so consumers can distinguish "quiet"
        from "unknown"."""
        return {
            "fair_probabilities": self.fair.as_dict() if self.fair else None,
            "bookmaker_count": self.fair.bookmaker_count if self.fair else 0,
            "consensus_score": self.consensus.score if self.consensus else None,
            "divergence_score": self.divergence.score if self.divergence else None,
            "divergence_outliers": list(self.divergence.outliers) if self.divergence else [],
            "confidence_score": self.confidence.score if self.confidence else None,
            "confidence_velocity": self.confidence.velocity if self.confidence else None,
            "volatility_score": self.volatility.score if self.volatility else None,
            "sharp_movement_score": self.sharp.score if self.sharp else None,
            "sharp_direction": self.sharp.direction if self.sharp else 0,
            "snapshots": self.snapshots,
        }


class MarketStateEngine:
    """Composes the six market engines into one market_state pass."""

    def __init__(self, *, observe_metrics: bool = True) -> None:
        self._observe = observe_metrics

    def compute(self, history: list[OddsTick]) -> MarketState:
        # Each of these two scans is O(n) over the tick history; every
        # subengine below independently recomputed its own copy before
        # (fair/consensus/divergence/confidence each called
        # latest_fair_probs_by_book; volatility/sharp each called
        # fair_prob_points) — up to 4x and 2x redundant per compute()
        # call respectively. Compute once, pass through.
        books = latest_fair_probs_by_book(history)
        points = [v for _, v in fair_prob_points(history)]
        fair = fair_probabilities(history, books=books)
        state = MarketState(
            fair=fair,
            consensus=consensus(history, books=books),
            divergence=divergence(history, books=books),
            confidence=market_confidence(history, books=books, fair=fair),
            volatility=volatility(history, points=points),
            sharp=sharp_movement(history, points=points),
            snapshots=len({t.captured_at for t in history}),
        )
        if self._observe:
            if state.consensus is not None:
                MARKET_CONSENSUS_SCORE.observe(state.consensus.score)
            if state.divergence is not None:
                MARKET_DIVERGENCE_SCORE.observe(state.divergence.score)
            if state.confidence is not None:
                MARKET_CONFIDENCE_SCORE.observe(state.confidence.score)
            if state.volatility is not None:
                MARKET_VOLATILITY_SCORE.observe(state.volatility.score)
            if (
                state.sharp is not None
                and state.sharp.score >= SHARP_COUNTER_THRESHOLD
            ):
                MARKET_SHARP_MOVEMENTS_TOTAL.inc()
        return state
