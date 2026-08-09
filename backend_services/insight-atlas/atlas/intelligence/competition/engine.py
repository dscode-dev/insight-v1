"""Competition Intelligence — Intelligence Maturity Part 4.

Atlas understands matches; this engine makes it understand
COMPETITIONS (World Cup, Champions League, Brasileirão, Libertadores):
deterministic aggregates over the trend history + outcome log scoped
to one competition_id.

  volatility        — share of trends that are volatility/churn types
  confidence        — mean trend confidence
  fragmentation     — share of divergence/fragmentation/disagreement
  trend_density     — trends per distinct match
  signal_density    — mean co-occurring signals per trend
  confirmation_rate — confirmed / resolved outcomes
  failure_rate      — failed / resolved outcomes
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendEventRow, TrendOutcomeRow

COMPETITION_PROFILES_TOTAL = Counter(
    "competition_profiles_total",
    "Competition intelligence profiles computed.",
)

# Trend types that indicate market churn vs structural disagreement.
_VOLATILITY_TYPES = (
    "VOLATILITY_INCREASE", "SHARP_MARKET_MOVE", "market_acceleration",
)
_FRAGMENTATION_TYPES = (
    "MARKET_DIVERGENCE", "MARKET_FRAGMENTATION", "market_disagreement",
    "market_anomaly",
)
_MOMENTUM_CATEGORY = "pulse"
_EVENT_CATEGORY = "sentinel"


@dataclass(frozen=True, slots=True)
class CompetitionProfile:
    competition_id: UUID
    matches: int
    trends: int
    volatility: float          # 0..1 share of churn trends
    confidence: float          # mean trend confidence
    fragmentation: float       # 0..1 share of disagreement trends
    trend_density: float       # trends per match
    signal_density: float      # mean signals per trend
    momentum_share: float      # share of pulse trends
    event_share: float         # share of sentinel trends
    confirmation_rate: float | None
    failure_rate: float | None

    def to_wire(self) -> dict:
        return {
            "competition_id": str(self.competition_id),
            "matches": self.matches,
            "trends": self.trends,
            "volatility": round(self.volatility, 4),
            "confidence": round(self.confidence, 4),
            "fragmentation": round(self.fragmentation, 4),
            "trend_density": round(self.trend_density, 2),
            "signal_density": round(self.signal_density, 2),
            "momentum_share": round(self.momentum_share, 4),
            "event_share": round(self.event_share, 4),
            "confirmation_rate": (
                round(self.confirmation_rate, 4)
                if self.confirmation_rate is not None else None
            ),
            "failure_rate": (
                round(self.failure_rate, 4)
                if self.failure_rate is not None else None
            ),
        }


class CompetitionIntelligenceEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        window_days: int = 90,
    ) -> None:
        self._sf = session_factory
        # This profile feeds RegimeEngine.classify — i.e. the
        # competition's CURRENT regime. It previously aggregated the
        # entire lifetime of the table with no time filter, so shares
        # converged and the regime froze: a competition that turned
        # volatile this month could never cross `volatile_min` because
        # it was diluted by years of history. 90 days matches the window
        # CrossMatchEngine and MetaTrendEngine already use.
        self._window_days = window_days

    async def profile(
        self, competition_id: UUID
    ) -> CompetitionProfile | None:
        """Deterministic competition aggregate over the recent window.
        None when the competition has produced no trends in it."""
        t = TrendEventRow
        since = datetime.now(timezone.utc) - timedelta(days=self._window_days)
        stmt = select(
            func.count(),
            func.count(func.distinct(t.canonical_match_id)),
            func.avg(t.confidence),
            func.sum(case((t.trend_type.in_(_VOLATILITY_TYPES), 1), else_=0)),
            func.sum(case((t.trend_type.in_(_FRAGMENTATION_TYPES), 1), else_=0)),
            func.sum(case((t.category == _MOMENTUM_CATEGORY, 1), else_=0)),
            func.sum(case((t.category == _EVENT_CATEGORY, 1), else_=0)),
        ).where(t.competition_id == competition_id, t.detected_at >= since)
        async with self._sf() as session:
            row = (await session.execute(stmt)).one()
            trends = int(row[0] or 0)
            if trends == 0:
                return None
            # Signal count used to stream EVERY trend's `signals` column
            # into process memory just to sum len() — that is an
            # aggregate, so let the database do it. The array-length
            # function is dialect-specific: the column is JSONB on
            # Postgres (migration 0006) but plain JSON on the SQLite
            # used by tests, and calling the wrong one fails at runtime
            # — so a naive `json_array_length` would have passed CI and
            # broken production.
            dialect = session.bind.dialect.name if session.bind is not None else ""
            array_length = (
                func.jsonb_array_length if dialect == "postgresql"
                else func.json_array_length
            )
            signal_total = int((await session.execute(
                select(func.coalesce(func.sum(array_length(t.signals)), 0))
                .where(t.competition_id == competition_id, t.detected_at >= since)
            )).scalar_one() or 0)

            o = TrendOutcomeRow
            outcome_row = (await session.execute(
                select(
                    func.sum(case((o.outcome == "confirmed", 1), else_=0)),
                    func.sum(case((o.outcome == "failed", 1), else_=0)),
                ).where(o.competition_id == competition_id, o.closed_at >= since)
            )).one()

        matches = int(row[1] or 1)
        confirmed = int(outcome_row[0] or 0)
        failed = int(outcome_row[1] or 0)
        resolved = confirmed + failed
        COMPETITION_PROFILES_TOTAL.inc()
        return CompetitionProfile(
            competition_id=competition_id,
            matches=matches,
            trends=trends,
            volatility=int(row[3] or 0) / trends,
            confidence=float(row[2] or 0.0),
            fragmentation=int(row[4] or 0) / trends,
            trend_density=trends / matches,
            signal_density=signal_total / trends,
            momentum_share=int(row[5] or 0) / trends,
            event_share=int(row[6] or 0) / trends,
            confirmation_rate=confirmed / resolved if resolved else None,
            failure_rate=failed / resolved if resolved else None,
        )

    async def active_competitions(self, *, limit: int = 20) -> list[UUID]:
        """Competitions with the most recent trend activity."""
        t = TrendEventRow
        stmt = (
            select(t.competition_id, func.max(t.detected_at).label("latest"))
            .where(t.competition_id.is_not(None))
            .group_by(t.competition_id)
            .order_by(func.max(t.detected_at).desc())
            .limit(limit)
        )
        async with self._sf() as session:
            rows = (await session.execute(stmt)).all()
        return [
            r[0] if isinstance(r[0], UUID) else UUID(str(r[0]))
            for r in rows
            if r[0] is not None
        ]

    async def latest_match(self, competition_id: UUID) -> UUID | None:
        """The competition's most recently active match — the anchor
        for competition-scoped meta observations."""
        t = TrendEventRow
        stmt = (
            select(t.canonical_match_id)
            .where(t.competition_id == competition_id)
            .order_by(t.detected_at.desc())
            .limit(1)
        )
        async with self._sf() as session:
            value = (await session.execute(stmt)).scalar_one_or_none()
        if value is None:
            return None
        return value if isinstance(value, UUID) else UUID(str(value))
