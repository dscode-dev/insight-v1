"""Historical Outcome Intelligence — Intelligence Maturity Part 2.

Answers "what usually happens after this?" as a pure frequency
distribution over the trend_outcomes log:

    pressure_building → 68% confirmed / 22% expired / 10% failed

Descriptive history, NOT a forecast: the rates are exact ratios of
recorded outcomes, attached to trends as auditable context.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendOutcomeRow
from atlas.trends.models import TrendType

HISTORICAL_OUTCOMES_TOTAL = Counter(
    "historical_outcomes_total",
    "Historical outcome profiles served (with sufficient sample).",
)


@dataclass(frozen=True, slots=True)
class HistoricalOutcomeProfile:
    trend_type: str
    scope: str
    sample: int
    confirmed_rate: float
    failed_rate: float
    expired_rate: float

    def to_wire(self) -> dict:
        return {
            "scope": self.scope,
            "sample": self.sample,
            "confirmed_rate": round(self.confirmed_rate, 4),
            "failed_rate": round(self.failed_rate, 4),
            "expired_rate": round(self.expired_rate, 4),
        }


class HistoricalOutcomeEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        min_sample: int = 5,
    ) -> None:
        self._sf = session_factory
        self._min_sample = min_sample

    async def profile(
        self,
        trend_type: TrendType,
        *,
        competition_id: UUID | None = None,
    ) -> HistoricalOutcomeProfile | None:
        """Outcome distribution for one trend type. Prefers the
        competition scope; falls back to global when the competition
        sample is below min_sample. None when even the global sample
        is insufficient."""
        if competition_id is not None:
            scoped = await self._aggregate(trend_type, competition_id)
            if scoped is not None:
                return scoped
        return await self._aggregate(trend_type, None)

    async def _aggregate(
        self, trend_type: TrendType, competition_id: UUID | None
    ) -> HistoricalOutcomeProfile | None:
        conditions = [TrendOutcomeRow.trend_type == trend_type.value]
        if competition_id is not None:
            conditions.append(TrendOutcomeRow.competition_id == competition_id)
        stmt = select(
            func.count(),
            func.sum(case((TrendOutcomeRow.outcome == "confirmed", 1), else_=0)),
            func.sum(case((TrendOutcomeRow.outcome == "failed", 1), else_=0)),
            func.sum(case((TrendOutcomeRow.outcome == "expired", 1), else_=0)),
        ).where(*conditions)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
        sample = int(row[0] or 0)
        if sample < self._min_sample:
            return None
        HISTORICAL_OUTCOMES_TOTAL.inc()
        scope = f"competition:{competition_id}" if competition_id else "global"
        return HistoricalOutcomeProfile(
            trend_type=trend_type.value,
            scope=scope,
            sample=sample,
            confirmed_rate=int(row[1] or 0) / sample,
            failed_rate=int(row[2] or 0) / sample,
            expired_rate=int(row[3] or 0) / sample,
        )
