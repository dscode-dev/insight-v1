"""Lifecycle persistence — atlas.trend_lifecycle.

One row per TrendInstance, upserted as the state machine advances.
trend_events rows are NEVER touched: the lifecycle is a separate
record over them, keyed by instance_id, with the full parallel
histories stored as JSON so every state transition is reproducible
from the stored evidence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendLifecycleRow
from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.models import TrendType

logger = logging.getLogger(__name__)

_OPEN_STATES = (
    TrendLifecycleState.ACTIVE.value,
    TrendLifecycleState.STRENGTHENING.value,
    TrendLifecycleState.WEAKENING.value,
)


class TrendLifecycleRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def open_instances(self, canonical_match_id: UUID) -> list[TrendInstance]:
        """Every non-terminal instance for one match."""
        async with self._sf() as session:
            stmt = select(TrendLifecycleRow).where(
                TrendLifecycleRow.canonical_match_id == canonical_match_id,
                TrendLifecycleRow.current_state.in_(_OPEN_STATES),
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_instance(r) for r in rows]

    async def save(self, instance: TrendInstance) -> None:
        """Upsert one instance (insert on first observation, full-state
        update afterwards)."""
        async with self._sf() as session:
            row = await session.get(TrendLifecycleRow, instance.instance_id)
            if row is None:
                session.add(_to_row(instance))
            else:
                row.current_state = instance.current_state.value
                row.direction = instance.direction
                row.last_seen_at = instance.last_seen_at
                row.trend_ids = list(instance.trend_ids)
                row.strength_history = list(instance.strength_history)
                row.confidence_history = list(instance.confidence_history)
                row.evidence_history = list(instance.evidence_history)
                row.state_history = list(instance.state_history)
                row.confirmed_by = instance.confirmed_by
                row.failed_by = instance.failed_by
            await session.commit()

    async def save_many(self, instances: list[TrendInstance]) -> None:
        for instance in instances:
            await self.save(instance)

    async def history(
        self, canonical_match_id: UUID, *, limit: int = 200
    ) -> list[TrendInstance]:
        async with self._sf() as session:
            stmt = (
                select(TrendLifecycleRow)
                .where(TrendLifecycleRow.canonical_match_id == canonical_match_id)
                .order_by(TrendLifecycleRow.created_at.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_instance(r) for r in rows]


def _to_row(i: TrendInstance) -> TrendLifecycleRow:
    return TrendLifecycleRow(
        instance_id=i.instance_id,
        canonical_match_id=i.canonical_match_id,
        trend_type=i.trend_type.value,
        direction=i.direction,
        current_state=i.current_state.value,
        created_at=i.created_at,
        last_seen_at=i.last_seen_at,
        trend_ids=list(i.trend_ids),
        strength_history=list(i.strength_history),
        confidence_history=list(i.confidence_history),
        evidence_history=list(i.evidence_history),
        state_history=list(i.state_history),
        confirmed_by=i.confirmed_by,
        failed_by=i.failed_by,
    )


def _aware(dt: datetime) -> datetime:
    """SQLite round-trips drop tzinfo; the engine does tz-aware
    arithmetic, so normalise on read."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _to_instance(row: TrendLifecycleRow) -> TrendInstance:
    return TrendInstance(
        instance_id=row.instance_id,
        canonical_match_id=row.canonical_match_id,
        trend_type=TrendType(row.trend_type),
        direction=row.direction,
        created_at=_aware(row.created_at),
        last_seen_at=_aware(row.last_seen_at),
        current_state=TrendLifecycleState(row.current_state),
        trend_ids=list(row.trend_ids or []),
        strength_history=list(row.strength_history or []),
        confidence_history=list(row.confidence_history or []),
        evidence_history=list(row.evidence_history or []),
        state_history=list(row.state_history or []),
        confirmed_by=row.confirmed_by,
        failed_by=row.failed_by,
    )
