"""Trend Continuation Intelligence — Intelligence Maturity Part 7.

Measures how long trend types historically PERSIST:

    market_conviction historically lasts avg 38 min
    pressure_building historically lasts avg 22 min

These are RECORDED FREQUENCIES over closed lifecycle instances —
descriptive memory, never a forecast.

Naming note: the wire keys `continuation_probability` /
`termination_probability` are retained for backwards compatibility, but
they are emitted ALONGSIDE `historical_continuation_rate` /
`historical_termination_rate` / `observed_median_duration_seconds`.
A key literally named "probability of a future event" is
indistinguishable from a forecast to a downstream consumer who hasn't
read this module — and a consumer rendering "72% chance this trend
continues" is exactly the output Atlas is forbidden to produce. New
consumers should read the `historical_*` keys; the old ones will be
dropped in a future contract version.
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
    # Explicit terminal-state counts. `termination_probability` used to
    # be derived as `(sample - confirmed) / sample`, which silently
    # classified ANY other outcome value as "terminated" — the sibling
    # historical_outcomes engine already counted failed/expired
    # explicitly. Carrying the raw counts also lets a consumer see the
    # sample behind a rate instead of a bare rounded ratio.
    confirmed: int = 0
    failed: int = 0
    expired: int = 0

    def to_wire(self) -> dict:
        return {
            "scope": self.scope,
            "sample": self.sample,
            "expected_duration_seconds": round(self.expected_duration_seconds, 1),
            # Descriptive names — what these numbers actually are.
            "observed_median_duration_seconds": round(
                self.expected_duration_seconds, 1
            ),
            "historical_continuation_rate": round(self.continuation_probability, 4),
            "historical_termination_rate": round(self.termination_probability, 4),
            "confirmed": self.confirmed,
            "failed": self.failed,
            "expired": self.expired,
            # Legacy aliases — see the module docstring. Additive-only
            # contract rule: existing consumers keep working unchanged.
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
            func.sum(case((TrendOutcomeRow.outcome == "failed", 1), else_=0)),
            func.sum(case((TrendOutcomeRow.outcome == "expired", 1), else_=0)),
        ).where(*conditions)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
        sample = int(row[0] or 0)
        if sample < self._min_sample:
            return None
        confirmed = int(row[2] or 0)
        failed = int(row[3] or 0)
        expired = int(row[4] or 0)
        CONTINUATION_PROFILES_TOTAL.inc()
        scope = f"competition:{competition_id}" if competition_id else "global"
        return TrendContinuationProfile(
            trend_type=trend_type.value,
            scope=scope,
            sample=sample,
            expected_duration_seconds=float(row[1] or 0.0),
            continuation_probability=confirmed / sample,
            # Explicitly failed + expired, NOT "everything that isn't
            # confirmed" — an unexpected outcome value must not silently
            # inflate the termination rate.
            termination_probability=(failed + expired) / sample,
            confirmed=confirmed,
            failed=failed,
            expired=expired,
        )
