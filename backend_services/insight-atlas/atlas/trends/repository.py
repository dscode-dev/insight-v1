"""Trend persistence — the durable trend history.

Trends are appended (never updated): the timeline of what Atlas
detected, when, with what evidence. Persist-then-publish ordering means
a failed stream publish is replayable from this table.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendEventRow
from atlas.trends.models import CATEGORY_OF, Severity, Trend, TrendType

logger = logging.getLogger(__name__)


class TrendRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(self, trend: Trend) -> bool:
        """Append one trend. Idempotent on trend_id — a duplicate insert
        (replay) is a no-op returning False."""
        async with self._sf() as session:
            session.add(
                TrendEventRow(
                    trend_id=trend.trend_id,
                    trend_type=trend.trend_type.value,
                    category=trend.category.value,
                    canonical_match_id=trend.canonical_match_id,
                    competition_id=trend.competition_id,
                    minute=trend.minute,
                    strength=trend.strength,
                    confidence=trend.confidence,
                    direction=trend.direction,
                    evidence=trend.evidence,
                    detected_at=trend.detected_at,
                    agent=trend.agent,
                    severity=trend.severity.value if trend.severity else "",
                    title=trend.title,
                    summary=trend.summary,
                    signals=list(trend.signals),
                    chart_data=trend.chart_data,
                    publish_score=trend.publish_score,
                    publication_tier=trend.publication_tier or "",
                    lifecycle_state=trend.lifecycle_state or "",
                    correlation_ids=list(trend.correlation_ids),
                    meaning=trend.meaning or "",
                    meaning_category=trend.meaning_category or "",
                    meaning_confidence=trend.meaning_confidence,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "trend_duplicate_skipped", extra={"trend_id": str(trend.trend_id)}
                )
                return False
            return True

    async def history(
        self,
        canonical_match_id: UUID,
        *,
        trend_type: TrendType | None = None,
        limit: int = 200,
    ) -> list[Trend]:
        """Ordered (oldest→newest) trend timeline for one match."""
        async with self._sf() as session:
            stmt = select(TrendEventRow).where(
                TrendEventRow.canonical_match_id == canonical_match_id
            )
            if trend_type is not None:
                stmt = stmt.where(TrendEventRow.trend_type == trend_type.value)
            stmt = stmt.order_by(TrendEventRow.detected_at.asc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_trend(r) for r in rows]


def _to_trend(row: TrendEventRow) -> Trend:
    trend_type = TrendType(row.trend_type)
    return Trend(
        trend_id=row.trend_id,
        trend_type=trend_type,
        category=CATEGORY_OF[trend_type],
        canonical_match_id=row.canonical_match_id,
        competition_id=row.competition_id,
        minute=row.minute,
        strength=row.strength,
        confidence=row.confidence,
        direction=row.direction,
        evidence=row.evidence or {},
        detected_at=row.detected_at,
        agent=row.agent or "",
        severity=Severity(row.severity) if row.severity else None,
        title=row.title or "",
        summary=row.summary or "",
        signals=list(row.signals or []),
        chart_data=row.chart_data or {},
        publish_score=row.publish_score,
        publication_tier=row.publication_tier or None,
        lifecycle_state=row.lifecycle_state or None,
        correlation_ids=list(row.correlation_ids or []),
        meaning=row.meaning or None,
        meaning_category=row.meaning_category or None,
        meaning_confidence=row.meaning_confidence,
    )
