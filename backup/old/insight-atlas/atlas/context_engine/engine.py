"""Recalculation decision + execution.

Decides whether to recalculate a match's context on this tick (one of
three triggers) and, when so, runs the pure recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from prometheus_client import Counter

from atlas.context_engine.checkpoints import CheckpointTracker
from atlas.context_engine.recompute import recompute_context
from atlas.event_impact import Impact

CONTEXT_RECALCULATION_TOTAL = Counter(
    "context_recalculation_total",
    "Context recalculations performed by Atlas, by trigger.",
    ["trigger"],
)


@dataclass(frozen=True, slots=True)
class RecalcDecision:
    recalc: bool
    trigger: str
    reason: str
    checkpoints: tuple[int, ...] = field(default_factory=tuple)


class ContextRecalculationEngine:
    """Event/odds/time triggered context recalculation."""

    def __init__(self, *, checkpoint_tracker: CheckpointTracker) -> None:
        self._cp = checkpoint_tracker

    async def evaluate(
        self,
        *,
        canonical_match_id: UUID,
        impact: Impact,
        minute: int | None = None,
        odds_shift: bool = False,
    ) -> RecalcDecision:
        """Decide whether to recalculate. Precedence: critical event →
        odds shift → time checkpoint."""
        if impact == Impact.CRITICAL:
            return RecalcDecision(True, "event", "critical_event")
        if odds_shift:
            return RecalcDecision(True, "odds", "meaningful_odds_shift")
        if minute is not None:
            due = await self._cp.due(canonical_match_id, minute)
            if due:
                return RecalcDecision(True, "time", f"checkpoints={due}", tuple(due))
        return RecalcDecision(False, "", "")

    def recompute(
        self,
        *,
        canonical_match_id: UUID,
        minute: int | None,
        odds_context: dict[str, Any] | None = None,
        prior: dict[str, Any] | None = None,
        market_state: dict[str, Any] | None = None,
        intelligence_state: dict[str, Any] | None = None,
        trigger: str = "event",
    ) -> dict[str, Any]:
        CONTEXT_RECALCULATION_TOTAL.labels(trigger=trigger or "event").inc()
        return recompute_context(
            canonical_match_id=canonical_match_id,
            minute=minute,
            odds_context=odds_context,
            prior=prior,
            market_state=market_state,
            intelligence_state=intelligence_state,
        )
