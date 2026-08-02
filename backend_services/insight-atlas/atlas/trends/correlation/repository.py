"""Correlation persistence — atlas.correlated_trends."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import CorrelatedTrendRow
from atlas.trends.correlation.models import CorrelatedTrend, CorrelationType

logger = logging.getLogger(__name__)


class CorrelatedTrendRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(self, correlated: CorrelatedTrend) -> bool:
        async with self._sf() as session:
            session.add(
                CorrelatedTrendRow(
                    correlation_id=correlated.id,
                    canonical_match_id=correlated.canonical_match_id,
                    correlation_type=correlated.correlation_type.value,
                    member_trends=list(correlated.member_trends),
                    confidence=correlated.confidence,
                    strength=correlated.strength,
                    evidence=correlated.evidence,
                    created_at=correlated.created_at,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "correlated_trend_duplicate_skipped",
                    extra={"correlation_id": str(correlated.id)},
                )
                return False
            return True

    async def history(
        self, canonical_match_id: UUID, *, limit: int = 100
    ) -> list[CorrelatedTrend]:
        async with self._sf() as session:
            stmt = (
                select(CorrelatedTrendRow)
                .where(CorrelatedTrendRow.canonical_match_id == canonical_match_id)
                .order_by(CorrelatedTrendRow.created_at.asc())
                .limit(limit)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [
                CorrelatedTrend(
                    id=r.correlation_id,
                    canonical_match_id=r.canonical_match_id,
                    correlation_type=CorrelationType(r.correlation_type),
                    member_trends=list(r.member_trends or []),
                    confidence=r.confidence,
                    strength=r.strength,
                    evidence=r.evidence or {},
                    created_at=r.created_at,
                )
                for r in rows
            ]
