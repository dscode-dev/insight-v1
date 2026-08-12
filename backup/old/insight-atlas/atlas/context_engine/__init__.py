"""Context Recalculation Engine — Sprint 6.2 Part 3.

Context changes even without new events (0-0 at 10' is not 0-0 at 85').
This engine recalculates momentum / pressure / game-state / contextual
probabilities on three triggers — event-driven (critical events),
odds-driven (meaningful odds shifts) and time-driven (minute
checkpoints) — reusing the existing feature/context stores.
"""

from atlas.context_engine.checkpoints import (
    DEFAULT_CHECKPOINTS,
    CheckpointTracker,
    InMemoryCheckpointStore,
    RedisCheckpointStore,
)
from atlas.context_engine.engine import (
    ContextRecalculationEngine,
    RecalcDecision,
)
from atlas.context_engine.recompute import recompute_context
from atlas.context_engine.store import (
    InMemoryMatchContextStore,
    MatchContextStore,
    RedisMatchContextStore,
)

__all__ = [
    "DEFAULT_CHECKPOINTS",
    "CheckpointTracker",
    "ContextRecalculationEngine",
    "InMemoryCheckpointStore",
    "InMemoryMatchContextStore",
    "MatchContextStore",
    "RecalcDecision",
    "RedisCheckpointStore",
    "RedisMatchContextStore",
    "recompute_context",
]
