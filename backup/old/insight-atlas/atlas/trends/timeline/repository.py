"""Timeline persistence — append-only over atlas.trend_timeline."""

from __future__ import annotations

import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendTimelineRow
from atlas.trends.timeline.models import TrendTimeline, TrendTimelineEntry

logger = logging.getLogger(__name__)


class TrendTimelineRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def append(self, cluster_id: UUID, entry: TrendTimelineEntry) -> None:
        """Append one entry. Append-only: rows are never updated."""
        async with self._sf() as session:
            session.add(
                TrendTimelineRow(
                    id=uuid4(),
                    cluster_id=cluster_id,
                    ts=entry.timestamp,
                    trend_id=entry.trend_id,
                    trend_type=entry.trend_type,
                    lifecycle_state=entry.lifecycle_state,
                    confidence=entry.confidence,
                    strength=entry.strength,
                    summary=entry.summary,
                    meaning=entry.meaning,
                )
            )
            await session.commit()

    async def get(self, cluster_id: UUID, *, limit: int = 500) -> TrendTimeline:
        """The ordered (oldest→newest) timeline of one story."""
        async with self._sf() as session:
            stmt = (
                select(TrendTimelineRow)
                .where(TrendTimelineRow.cluster_id == cluster_id)
                .order_by(TrendTimelineRow.ts.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
        return TrendTimeline(
            cluster_id=cluster_id,
            entries=[
                TrendTimelineEntry(
                    timestamp=r.ts,
                    trend_id=r.trend_id,
                    trend_type=r.trend_type,
                    lifecycle_state=r.lifecycle_state,
                    confidence=r.confidence,
                    strength=r.strength,
                    summary=r.summary,
                    meaning=r.meaning,
                )
                for r in rows
            ],
        )
