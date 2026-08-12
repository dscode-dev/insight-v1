"""Trend lifecycle domain — Sprint 1.5 Part 1.

A TrendInstance is the EVOLUTION of one detected pattern over time:
the same (match, trend_type) observed repeatedly is one instance whose
state machine moves through

    ACTIVE → STRENGTHENING / WEAKENING → CONFIRMED / FAILED / EXPIRED

Terminal states (CONFIRMED, FAILED, EXPIRED) close the instance; a
later observation of the same type opens a NEW instance. trend_events
rows are never mutated — the lifecycle is a separate, append-friendly
state machine over them.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from atlas.trends.models import TrendType


class TrendLifecycleState(str, enum.Enum):
    ACTIVE = "active"
    STRENGTHENING = "strengthening"
    WEAKENING = "weakening"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXPIRED = "expired"

    @property
    def terminal(self) -> bool:
        return self in (
            TrendLifecycleState.CONFIRMED,
            TrendLifecycleState.FAILED,
            TrendLifecycleState.EXPIRED,
        )


@dataclass
class TrendInstance:
    """One evolving trend. Histories are parallel, append-only lists —
    entry i of each history describes observation i, so the full
    evolution is reproducible from the stored record."""

    instance_id: UUID
    canonical_match_id: UUID
    trend_type: TrendType
    direction: int
    created_at: datetime
    last_seen_at: datetime
    current_state: TrendLifecycleState
    trend_ids: list[str] = field(default_factory=list)
    strength_history: list[float] = field(default_factory=list)
    confidence_history: list[float] = field(default_factory=list)
    evidence_history: list[dict[str, Any]] = field(default_factory=list)
    # Sprint 2 (A2) — every state the instance has been in, in order.
    # Exposed on the wire as the trend timeline so consumers see the
    # evolution without querying historical events.
    state_history: list[str] = field(default_factory=list)
    confirmed_by: str | None = None
    failed_by: str | None = None

    @property
    def observation_count(self) -> int:
        return len(self.strength_history)

    def timeline(self) -> dict[str, Any]:
        """Contract V3 timeline view: prior states (everything before
        the current one) + identity for deeper queries."""
        return {
            "instance_id": str(self.instance_id),
            "previous_states": list(self.state_history[:-1]),
            "current_state": self.current_state.value,
            "observation_count": self.observation_count,
        }

    @classmethod
    def open(
        cls,
        *,
        canonical_match_id: UUID,
        trend_type: TrendType,
        direction: int,
        now: datetime,
    ) -> "TrendInstance":
        return cls(
            instance_id=uuid4(),
            canonical_match_id=canonical_match_id,
            trend_type=trend_type,
            direction=direction,
            created_at=now,
            last_seen_at=now,
            current_state=TrendLifecycleState.ACTIVE,
        )


@dataclass(frozen=True, slots=True)
class LifecycleRule:
    """Per-trend-type lifecycle policy. All thresholds configurable.

    confirm_categories — impact categories observed on the match that
        confirm an OPEN instance (e.g. a goal confirms pressure_building).
    confirm_sustain — observation count at which the instance confirms
        by sheer reinforcement ("sustained movement" / "continued
        superiority"). None = no sustain-based confirmation.
    fail_on_reverse_direction — a same-type observation with the
        opposite direction fails the instance (the trend reversed).
    fail_types — other trend types whose appearance fails the instance.
        Value True requires the failing trend to OPPOSE the instance's
        direction (or, when the instance is direction-less, to carry a
        sign flip in its evidence); False fails on any appearance.
    """

    confirm_categories: frozenset[str] = frozenset()
    confirm_sustain: int | None = None
    fail_on_reverse_direction: bool = False
    fail_types: dict[TrendType, bool] = field(default_factory=dict)


DEFAULT_LIFECYCLE_RULES: dict[TrendType, LifecycleRule] = {
    # Pressure building → confirmed by a goal; fails when momentum
    # swings to the opponent.
    TrendType.pressure_building: LifecycleRule(
        confirm_categories=frozenset({"goal"}),
        fail_types={TrendType.momentum_shift: True},
    ),
    # Market shift → confirmed by sustained movement (3 reinforcing
    # observations in the same direction); fails on reversal.
    TrendType.market_shift: LifecycleRule(
        confirm_sustain=3,
        fail_on_reverse_direction=True,
    ),
    TrendType.market_acceleration: LifecycleRule(
        confirm_sustain=2,
        fail_on_reverse_direction=True,
    ),
    # Dominance → confirmed by continued statistical superiority;
    # fails when the other side takes over (reversed dominance or an
    # opposing momentum shift).
    TrendType.dominance_pattern: LifecycleRule(
        confirm_sustain=3,
        fail_on_reverse_direction=True,
        fail_types={TrendType.momentum_shift: True},
    ),
    # Historical deviation → confirmed by sustained deviation.
    TrendType.historical_deviation: LifecycleRule(
        confirm_sustain=3,
        fail_on_reverse_direction=True,
    ),
    # Market intelligence (Magnus Absorption) — consensus regimes are
    # confirmed by reinforcement and failed by their opposite regime.
    TrendType.market_consensus_growing: LifecycleRule(
        confirm_sustain=3,
        fail_types={TrendType.market_consensus_weakening: False},
    ),
    TrendType.market_consensus_weakening: LifecycleRule(
        confirm_sustain=3,
        fail_types={TrendType.market_consensus_growing: False},
    ),
    TrendType.volatility_increase: LifecycleRule(
        confirm_sustain=3,
        fail_types={TrendType.volatility_decrease: False},
    ),
    TrendType.confidence_acceleration: LifecycleRule(
        confirm_sustain=3,
        fail_types={TrendType.confidence_decay: False},
    ),
    # A sharp move is confirmed when the market keeps repricing the
    # same way; it fails on a reversal of direction.
    TrendType.sharp_market_move: LifecycleRule(
        confirm_sustain=2,
        fail_on_reverse_direction=True,
    ),
}
