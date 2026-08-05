"""OddsRepository — full odds-history persistence.

Stores EVERY odds snapshot (not just the latest). The temporal
evolution of a market is reconstructable by ordering on `captured_at`.

Backed by the same async SQLAlchemy session factory the model registry
uses (Postgres in production, SQLite in tests).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.odds.models import OddsTick
from atlas.registry.models import OddsTickRow

logger = logging.getLogger(__name__)


class OddsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record(self, tick: OddsTick) -> bool:
        """Append one snapshot. Idempotent on canonical_event_id.

        Returns True when a new row was written, False when the
        canonical event was already persisted (duplicate delivery).
        """
        async with self._sf() as session:
            row = OddsTickRow(
                canonical_event_id=tick.canonical_event_id,
                provider=tick.provider,
                competition_id=tick.competition_id,
                match_id=tick.match_id,
                market=tick.market,
                bookmaker=tick.bookmaker,
                home=tick.home,
                draw=tick.draw,
                away=tick.away,
                captured_at=tick.captured_at,
                payload=tick.payload,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "odds_tick_duplicate_skipped",
                    extra={"canonical_event_id": str(tick.canonical_event_id)},
                )
                return False
            return True

    async def history(
        self,
        match_id: UUID,
        *,
        market: str | None = None,
        limit: int = 500,
    ) -> list[OddsTick]:
        """Return the MOST RECENT `limit` snapshots for a match, oldest
        first, optionally filtered to one market.

        Fetches DESC (newest first) so `limit` bounds the recent end of
        the timeline, then reverses in Python to hand back the
        documented oldest→newest order. The previous ASC+LIMIT query
        bounded the OLD end instead: once a match passed `limit` ticks,
        every caller (features, context, MarketStateEngine) would freeze
        on the same oldest 500 snapshots forever, never seeing anything
        newer — exactly backwards for a live-updating history.
        """
        async with self._sf() as session:
            stmt = select(OddsTickRow).where(OddsTickRow.match_id == match_id)
            if market is not None:
                stmt = stmt.where(OddsTickRow.market == market)
            stmt = stmt.order_by(OddsTickRow.captured_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_tick(r) for r in reversed(rows)]

    async def count_for_match(self, match_id: UUID) -> int:
        async with self._sf() as session:
            stmt = select(func.count()).select_from(OddsTickRow).where(
                OddsTickRow.match_id == match_id
            )
            return (await session.execute(stmt)).scalar_one()


def _to_tick(row: OddsTickRow) -> OddsTick:
    return OddsTick(
        canonical_event_id=row.canonical_event_id,
        provider=row.provider,
        competition_id=row.competition_id,
        match_id=row.match_id,
        market=row.market,
        bookmaker=row.bookmaker,
        home=row.home,
        draw=row.draw,
        away=row.away,
        captured_at=row.captured_at,
        payload=row.payload or {},
    )
