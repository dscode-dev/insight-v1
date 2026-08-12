"""Atlas Market Intelligence — Magnus Absorption (Sprint 1).

Deterministic market analysis over the persisted odds timeline:
fair probabilities, consensus, divergence, confidence, volatility and
sharp-movement detection, composed into the match context's
`market_state`. Internal-only margin math; public outputs describe
market behavior, never bookmaker economics.
"""

from atlas.market.confidence import ConfidenceResult, market_confidence
from atlas.market.consensus import ConsensusResult, consensus
from atlas.market.divergence import DivergenceResult, divergence
from atlas.market.fair_probability import (
    FairProbabilities,
    fair_prob_points,
    fair_probabilities,
)
from atlas.market.sharp import SharpMovementResult, sharp_movement
from atlas.market.state import MarketState, MarketStateEngine
from atlas.market.volatility import VolatilityResult, volatility

__all__ = [
    "ConfidenceResult",
    "ConsensusResult",
    "DivergenceResult",
    "FairProbabilities",
    "MarketState",
    "MarketStateEngine",
    "SharpMovementResult",
    "VolatilityResult",
    "consensus",
    "divergence",
    "fair_prob_points",
    "fair_probabilities",
    "market_confidence",
    "sharp_movement",
    "volatility",
]
