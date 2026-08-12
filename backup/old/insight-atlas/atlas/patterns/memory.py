"""Statistical pattern memory.

A pattern is the recurrence of one trend behaviour in one competition:

    pattern_key = {competition_id}:{trend_type}:{direction}

Every time a trend lifecycle instance reaches a terminal state, the
pattern's counters update: CONFIRMED is a success, FAILED a failure,
EXPIRED an occurrence that resolved neither way. The historical
success rate is confirmed / (confirmed + failed) — undecided outcomes
count toward occurrences but not the rate, so the rate reflects only
patterns that actually resolved.

This is what lets Atlas say "this market behaviour occurred 4 times
here and confirmed 72% of the time" — pure counting, fully auditable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import PatternMemoryRow
from atlas.trends.lifecycle.models import TrendInstance, TrendLifecycleState
from atlas.trends.models import TrendType

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

PATTERN_OBSERVATIONS_TOTAL = Counter(
    "pattern_observations_total",
    "Terminal lifecycle outcomes folded into pattern memory.",
    ["outcome"],
)


def pattern_key(
    competition_id: UUID | None, trend_type: TrendType, direction: int
) -> str:
    comp = str(competition_id) if competition_id else "global"
    return f"{comp}:{trend_type.value}:{direction}"


class PatternStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    pattern_id: str
    competition_id: UUID | None
    trend_type: TrendType
    direction: int
    occurrences: int = Field(ge=0)
    confirmed: int = Field(ge=0)
    failed: int = Field(ge=0)
    historical_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)

    def to_wire(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "occurrences": self.occurrences,
            "confirmed": self.confirmed,
            "failed": self.failed,
            "historical_success_rate": self.historical_success_rate,
        }


class PatternMemory:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record_outcome(
        self, instance: TrendInstance, competition_id: UUID | None
    ) -> PatternStats | None:
        """Fold one TERMINAL lifecycle instance into pattern memory.
        Non-terminal instances are ignored (return None)."""
        state = instance.current_state
        if not state.terminal:
            return None
        key = pattern_key(competition_id, instance.trend_type, instance.direction)
        # Read-modify-write on a shared counter row: two workers closing
        # instances for the same (competition, trend_type, direction)
        # concurrently would lose a count, and — worse — two concurrent
        # first-inserts of the same PK raised an UNCAUGHT IntegrityError
        # that propagated out of the trend pipeline and aborted the whole
        # tick BEFORE trends were persisted or published. Sibling
        # repositories (TrendRepository.record,
        # CorrelatedTrendRepository.record) already handled this; this
        # one didn't. Retry-once on the insert race, then fall through
        # to the increment path.
        for attempt in (0, 1):
            async with self._sf() as session:
                row = await session.get(PatternMemoryRow, key)
                if row is None:
                    row = PatternMemoryRow(
                        pattern_id=key,
                        competition_id=competition_id,
                        trend_type=instance.trend_type.value,
                        direction=instance.direction,
                        occurrences=0,
                        confirmed=0,
                        failed=0,
                    )
                    session.add(row)
                row.occurrences += 1
                if state == TrendLifecycleState.CONFIRMED:
                    row.confirmed += 1
                elif state == TrendLifecycleState.FAILED:
                    row.failed += 1
                row.updated_at = datetime.now(timezone.utc)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    if attempt == 0:
                        # Another worker inserted the row between our
                        # get() and commit() — retry, which now takes
                        # the increment branch.
                        logger.info(
                            "pattern_memory_insert_raced", extra={"pattern_id": key}
                        )
                        continue
                    logger.warning(
                        "pattern_memory_record_failed", extra={"pattern_id": key}
                    )
                    return None
                PATTERN_OBSERVATIONS_TOTAL.labels(outcome=state.value).inc()
                return _stats(row)
        return None

    async def lookup(
        self,
        competition_id: UUID | None,
        trend_type: TrendType,
        direction: int,
    ) -> PatternStats | None:
        """Known recurrence for this behaviour, or None when it has
        never been observed to a terminal outcome."""
        key = pattern_key(competition_id, trend_type, direction)
        async with self._sf() as session:
            row = await session.get(PatternMemoryRow, key)
            return _stats(row) if row is not None else None


def _stats(row: PatternMemoryRow) -> PatternStats:
    resolved = row.confirmed + row.failed
    rate = round(row.confirmed / resolved, 4) if resolved > 0 else None
    return PatternStats(
        pattern_id=row.pattern_id,
        competition_id=row.competition_id,
        trend_type=TrendType(row.trend_type),
        direction=row.direction,
        occurrences=row.occurrences,
        confirmed=row.confirmed,
        failed=row.failed,
        historical_success_rate=rate,
    )
