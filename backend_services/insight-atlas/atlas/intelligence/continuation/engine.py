"""Trend Continuation Intelligence — Intelligence Maturity Part 7.

Measures how long trend types historically PERSIST:

    market_conviction historically lasts avg 38 min
    pressure_building historically lasts avg 22 min

continuation_probability is the historical share of instances that
resolved by confirmation (the trend "carried through");
termination_probability is the share that failed or expired. These are
recorded frequencies — descriptive memory, not a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendOutcomeRow
from atlas.trends.models import TrendType

CONTINUATION_PROFILES_TOTAL = Counter(
    "continuation_profiles_total",
    "Trend continuation profiles served (with sufficient sample).",
)


@dataclass(frozen=True, slots=True)
class TrendContinuationProfile:
    trend_type: str
    scope: str
    sample: int
    expected_duration_seconds: float
    continuation_probability: float
    termination_probability: float

    def to_wire(self) -> dict:
        return {
            "scope": self.scope,
            "sample": self.sample,
            "expected_duration_seconds": round(self.expected_duration_seconds, 1),
            "continuation_probability": round(self.continuation_probability, 4),
            "termination_probability": round(self.termination_probability, 4),
        }


class ContinuationEngine:
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
    ) -> TrendContinuationProfile | None:
        """Persistence profile; competition scope preferred, global
        fallback, None below min_sample."""
        if competition_id is not None:
            scoped = await self._aggregate(trend_type, competition_id)
            if scoped is not None:
                return scoped
        return await self._aggregate(trend_type, None)

    async def _aggregate(
        self, trend_type: TrendType, competition_id: UUID | None
    ) -> TrendContinuationProfile | None:
        conditions = [TrendOutcomeRow.trend_type == trend_type.value]
        if competition_id is not None:
            conditions.append(TrendOutcomeRow.competition_id == competition_id)
        stmt = select(
            func.count(),
            func.avg(TrendOutcomeRow.duration_seconds),
            func.sum(case((TrendOutcomeRow.outcome == "confirmed", 1), else_=0)),
        ).where(*conditions)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
        sample = int(row[0] or 0)
        if sample < self._min_sample:
            return None
        confirmed = int(row[2] or 0)
        CONTINUATION_PROFILES_TOTAL.inc()
        scope = f"competition:{competition_id}" if competition_id else "global"
        return TrendContinuationProfile(
            trend_type=trend_type.value,
            scope=scope,
            sample=sample,
            expected_duration_seconds=float(row[1] or 0.0),
            continuation_probability=confirmed / sample,
            termination_probability=(sample - confirmed) / sample,
        )
