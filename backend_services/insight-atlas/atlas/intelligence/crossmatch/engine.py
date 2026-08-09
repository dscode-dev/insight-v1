"""Cross Match Intelligence — Intelligence Maturity Part 6.

Analyzes patterns spanning MULTIPLE matches of one scope (a team or a
competition): is Team X repeatedly causing market shifts? Is Team Y
repeatedly generating volatility? Is Competition Z producing abnormal
uncertainty?

Deterministic counting over the trend history joined with the
canonical match identity (team names) — pure recurrence facts, no
inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import CanonicalMatchRow, TrendEventRow

CROSSMATCH_PATTERNS_TOTAL = Counter(
    "crossmatch_patterns_total",
    "Cross-match profiles computed.",
    ["scope"],
)

_MARKET_SHIFT_TYPES = ("market_shift", "SHARP_MARKET_MOVE", "market_acceleration")
_VOLATILITY_TYPES = ("VOLATILITY_INCREASE", "market_acceleration", "SHARP_MARKET_MOVE")
_UNCERTAINTY_TYPES = ("MARKET_FRAGMENTATION", "MARKET_DIVERGENCE", "MARKET_UNCERTAINTY")


@dataclass(frozen=True, slots=True)
class CrossMatchProfile:
    scope: str                       # "team:<name>" | "competition:<id>"
    matches: int                     # distinct matches in the window
    market_shift_matches: int        # matches with ≥1 market-shift trend
    volatility_matches: int          # matches with ≥1 volatility trend
    uncertainty_matches: int         # matches with ≥1 uncertainty trend
    window_days: int

    @property
    def market_shift_rate(self) -> float:
        return self.market_shift_matches / self.matches if self.matches else 0.0

    @property
    def volatility_rate(self) -> float:
        return self.volatility_matches / self.matches if self.matches else 0.0

    @property
    def uncertainty_rate(self) -> float:
        return self.uncertainty_matches / self.matches if self.matches else 0.0

    def to_wire(self) -> dict:
        return {
            "scope": self.scope,
            "matches": self.matches,
            "market_shift_matches": self.market_shift_matches,
            "volatility_matches": self.volatility_matches,
            "uncertainty_matches": self.uncertainty_matches,
            "market_shift_rate": round(self.market_shift_rate, 4),
            "volatility_rate": round(self.volatility_rate, 4),
            "uncertainty_rate": round(self.uncertainty_rate, 4),
            "window_days": self.window_days,
        }


def _as_uuid(value) -> UUID:
    """SQLite returns UUID columns as strings; normalise."""
    return value if isinstance(value, UUID) else UUID(str(value))


class CrossMatchEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        window_days: int = 90,
    ) -> None:
        self._sf = session_factory
        self._window_days = window_days

    async def team_profile(self, team: str) -> CrossMatchProfile:
        match_ids = await self._team_matches(team)
        return await self._profile(f"team:{team}", match_ids)

    async def competition_profile(
        self, competition_id: UUID
    ) -> CrossMatchProfile:
        since = datetime.now(timezone.utc) - timedelta(days=self._window_days)
        stmt = (
            select(func.distinct(TrendEventRow.canonical_match_id))
            .where(
                TrendEventRow.competition_id == competition_id,
                TrendEventRow.detected_at >= since,
            )
        )
        async with self._sf() as session:
            match_ids = [
                _as_uuid(v)
                for v in (await session.execute(stmt)).scalars().all()
            ]
        return await self._profile(f"competition:{competition_id}", match_ids)

    async def _team_matches(self, team: str) -> list[UUID]:
        since = datetime.now(timezone.utc) - timedelta(days=self._window_days)
        # `kickoff IS NULL` used to be OR'd in unconditionally, so EVERY
        # match with an unknown kickoff entered the denominator
        # regardless of age — inflating `matches` against a numerator
        # that is (now) genuinely windowed. A row with no kickoff can't
        # be shown to be inside the window, so it stays out of both
        # sides rather than only out of one.
        stmt = select(CanonicalMatchRow.canonical_match_id).where(
            or_(
                CanonicalMatchRow.home_team == team,
                CanonicalMatchRow.away_team == team,
            ),
            CanonicalMatchRow.kickoff.is_not(None),
            CanonicalMatchRow.kickoff >= since,
        )
        async with self._sf() as session:
            return [
                _as_uuid(v)
                for v in (await session.execute(stmt)).scalars().all()
            ]

    async def _profile(
        self, scope: str, match_ids: list[UUID]
    ) -> CrossMatchProfile:
        if not match_ids:
            return CrossMatchProfile(
                scope=scope, matches=0, market_shift_matches=0,
                volatility_matches=0, uncertainty_matches=0,
                window_days=self._window_days,
            )
        t = TrendEventRow
        since = datetime.now(timezone.utc) - timedelta(days=self._window_days)

        async def distinct_matches(session, types: tuple[str, ...]) -> int:
            # `detected_at >= since` was MISSING here while the
            # denominator (`_team_matches`) was windowed — an unbounded
            # numerator over a windowed denominator, so the resulting
            # rates had no well-defined interpretation.
            stmt = select(
                func.count(func.distinct(t.canonical_match_id))
            ).where(
                t.canonical_match_id.in_(match_ids),
                t.trend_type.in_(types),
                t.detected_at >= since,
            )
            return int((await session.execute(stmt)).scalar_one() or 0)

        # One session for all three counts (was opening three).
        async with self._sf() as session:
            market_shift = await distinct_matches(session, _MARKET_SHIFT_TYPES)
            volatility = await distinct_matches(session, _VOLATILITY_TYPES)
            uncertainty = await distinct_matches(session, _UNCERTAINTY_TYPES)

        profile = CrossMatchProfile(
            scope=scope,
            matches=len(match_ids),
            market_shift_matches=market_shift,
            volatility_matches=volatility,
            uncertainty_matches=uncertainty,
            window_days=self._window_days,
        )
        CROSSMATCH_PATTERNS_TOTAL.labels(
            scope=scope.split(":", 1)[0]
        ).inc()
        return profile
