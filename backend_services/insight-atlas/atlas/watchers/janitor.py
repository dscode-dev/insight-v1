"""ClusterJanitor — Sprint 3.6 Part 10.

Atlas's story unit is the trend lifecycle instance; today instances
expire only ON-TOUCH (when a tick for their match arrives). The
janitor closes that gap: a periodic pass expires every open instance
whose last activity is older than the threshold — no trend arrival
required.

Multi-instance safety: rows are selected WITH FOR UPDATE SKIP LOCKED,
so two Atlas instances sweeping concurrently partition the work
instead of double-expiring (SQLite ignores the locking clause, which
is fine for tests).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendLifecycleRow
from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.models import TrendType
from atlas.watchers.base import Observation

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atlas.intelligence.market_memory import MarketMemoryEngine

logger = logging.getLogger(__name__)

ATLAS_CLUSTER_JANITOR_TOTAL = Counter(
    "atlas_cluster_janitor_total",
    "Janitor passes executed.",
)
ATLAS_CLUSTER_JANITOR_EXPIRED_TOTAL = Counter(
    "atlas_cluster_janitor_expired_total",
    "Open story instances expired by the janitor.",
)

_OPEN_STATES = (
    TrendLifecycleState.ACTIVE.value,
    TrendLifecycleState.STRENGTHENING.value,
    TrendLifecycleState.WEAKENING.value,
)


class ClusterJanitor:
    """Registered like a watcher (name/enabled/observe); produces no
    observations — its work is the expiry side effect."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        inactivity_seconds: int = 1800,
        batch: int = 100,
        enabled: bool = True,
        now=None,
        market_memory: "MarketMemoryEngine | None" = None,
    ) -> None:
        self._sf = session_factory
        self._inactivity = inactivity_seconds
        self._batch = batch
        self._enabled = enabled
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._memory = market_memory

    def name(self) -> str:
        return "cluster_janitor"

    def enabled(self) -> bool:
        return self._enabled

    async def observe(self) -> list[Observation]:
        expired = await self.sweep()
        if expired:
            logger.info("atlas_janitor_expired", extra={"count": expired})
        return []

    async def sweep(self) -> int:
        """One expiry pass. Returns how many instances expired."""
        ATLAS_CLUSTER_JANITOR_TOTAL.inc()
        cutoff = self._now() - timedelta(seconds=self._inactivity)
        expired = 0
        async with self._sf() as session:
            stmt = (
                select(TrendLifecycleRow)
                .where(
                    TrendLifecycleRow.current_state.in_(_OPEN_STATES),
                    TrendLifecycleRow.last_seen_at < cutoff,
                )
                .limit(self._batch)
                .with_for_update(skip_locked=True)
            )
            rows = (await session.execute(stmt)).scalars().all()
            now = self._now()
            closed: list[TrendInstance] = []
            for row in rows:
                row.current_state = TrendLifecycleState.EXPIRED.value
                history = list(row.state_history or [])
                history.append(TrendLifecycleState.EXPIRED.value)
                row.state_history = history
                row.last_seen_at = now
                expired += 1
                closed.append(TrendInstance(
                    instance_id=row.instance_id,
                    canonical_match_id=row.canonical_match_id,
                    trend_type=TrendType(row.trend_type),
                    direction=row.direction,
                    created_at=row.created_at,
                    last_seen_at=now,
                    current_state=TrendLifecycleState.EXPIRED,
                    trend_ids=list(row.trend_ids or []),
                    strength_history=list(row.strength_history or []),
                    confidence_history=list(row.confidence_history or []),
                    state_history=history,
                ))
            await session.commit()
        # Maturity 1.5: janitor expirations land in the outcome log
        # too (insert-once; competition scope unknown on this path).
        if self._memory is not None:
            for inst in closed:
                await self._memory.record_closure(inst)
        if expired:
            ATLAS_CLUSTER_JANITOR_EXPIRED_TOTAL.inc(expired)
        return expired
