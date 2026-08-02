"""Meta Trend Engine — Intelligence Maturity Part 3 (aggregation side).

Computes the recurrence aggregates that the meta-trend DETECTOR
(atlas/trends/meta.py) turns into META trends. The split follows the
watcher doctrine: this engine owns the queries/math, the detector owns
the thresholds, the watcher owns the schedule — no duplicated logic.

All aggregates are deterministic counts over the append-only
trend_outcomes log:

  underestimation/overestimation — confirmed directional market
      repricings toward/against a team (the market kept being wrong
      about them in the same direction)
  recurring volatility            — volatility-trend closures across
      distinct matches in the scope
  recurring confidence failure    — CONFIDENCE_ACCELERATION instances
      that FAILED
  recurring sharp reversal        — SHARP_MARKET_MOVE instances that
      FAILED (reversed direction)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from prometheus_client import Counter
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import TrendOutcomeRow

META_TRENDS_TOTAL = Counter(
    "meta_trends_total",
    "Meta trends detected.",
    ["trend_type"],
)

# Directional market repricing types — the basis of the
# under/overestimation aggregates.
_DIRECTIONAL_MARKET_TYPES = ("market_shift", "SHARP_MARKET_MOVE")
_VOLATILITY_TYPES = ("VOLATILITY_INCREASE",)


@dataclass(frozen=True, slots=True)
class TeamMarketStats:
    """Directional repricing record for one team in scope."""

    team: str
    toward_samples: int       # confirmed-or-not repricings toward the team
    toward_confirmed: int
    against_samples: int      # repricings against the team
    against_confirmed: int

    @property
    def toward_rate(self) -> float:
        return (
            self.toward_confirmed / self.toward_samples
            if self.toward_samples else 0.0
        )

    @property
    def against_rate(self) -> float:
        return (
            self.against_confirmed / self.against_samples
            if self.against_samples else 0.0
        )


@dataclass(frozen=True, slots=True)
class MetaScan:
    """Everything the meta detector needs for one scope."""

    scope: str
    teams: list[TeamMarketStats] = field(default_factory=list)
    volatility_closures: int = 0
    volatility_matches: int = 0
    confidence_failures: int = 0
    confidence_samples: int = 0
    sharp_reversals: int = 0
    sharp_samples: int = 0

    def to_state(self) -> dict:
        """The `intelligence_state.meta` context entry (JSON-safe)."""
        return {
            "scope": self.scope,
            "teams": [
                {
                    "team": t.team,
                    "toward_samples": t.toward_samples,
                    "toward_confirmed": t.toward_confirmed,
                    "toward_rate": round(t.toward_rate, 4),
                    "against_samples": t.against_samples,
                    "against_confirmed": t.against_confirmed,
                    "against_rate": round(t.against_rate, 4),
                }
                for t in self.teams
            ],
            "volatility_closures": self.volatility_closures,
            "volatility_matches": self.volatility_matches,
            "confidence_failures": self.confidence_failures,
            "confidence_samples": self.confidence_samples,
            "sharp_reversals": self.sharp_reversals,
            "sharp_samples": self.sharp_samples,
        }


class MetaTrendEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        window_days: int = 90,
    ) -> None:
        self._sf = session_factory
        self._window_days = window_days

    def _since(self) -> datetime:
        return datetime.now(timezone.utc) - timedelta(days=self._window_days)

    async def scan_competition(self, competition_id: UUID) -> MetaScan:
        o = TrendOutcomeRow
        scope_filter = [
            o.competition_id == competition_id,
            o.closed_at >= self._since(),
        ]
        async with self._sf() as session:
            # Team directional stats: home side is "toward" when
            # direction=+1; away side is "toward" when direction=-1.
            team_rows = (await session.execute(
                select(
                    o.home_team, o.away_team, o.direction, o.outcome,
                    func.count(),
                )
                .where(
                    *scope_filter,
                    o.trend_type.in_(_DIRECTIONAL_MARKET_TYPES),
                    o.direction != 0,
                )
                .group_by(o.home_team, o.away_team, o.direction, o.outcome)
            )).all()

            vol_row = (await session.execute(
                select(
                    func.count(),
                    func.count(func.distinct(o.canonical_match_id)),
                ).where(*scope_filter, o.trend_type.in_(_VOLATILITY_TYPES))
            )).one()

            conf_row = (await session.execute(
                select(
                    func.count(),
                    func.sum(case((o.outcome == "failed", 1), else_=0)),
                ).where(
                    *scope_filter,
                    o.trend_type == "CONFIDENCE_ACCELERATION",
                )
            )).one()

            sharp_row = (await session.execute(
                select(
                    func.count(),
                    func.sum(case((o.outcome == "failed", 1), else_=0)),
                ).where(*scope_filter, o.trend_type == "SHARP_MARKET_MOVE")
            )).one()

        stats: dict[str, dict[str, int]] = {}
        for home, away, direction, outcome, count in team_rows:
            toward = home if direction > 0 else away
            against = away if direction > 0 else home
            confirmed = outcome == "confirmed"
            for team, side in ((toward, "toward"), (against, "against")):
                if not team:
                    continue
                entry = stats.setdefault(
                    team,
                    {"toward_samples": 0, "toward_confirmed": 0,
                     "against_samples": 0, "against_confirmed": 0},
                )
                entry[f"{side}_samples"] += count
                if confirmed:
                    entry[f"{side}_confirmed"] += count

        teams = sorted(
            (
                TeamMarketStats(team=team, **values)
                for team, values in stats.items()
            ),
            key=lambda t: t.team,
        )
        return MetaScan(
            scope=f"competition:{competition_id}",
            teams=teams,
            volatility_closures=int(vol_row[0] or 0),
            volatility_matches=int(vol_row[1] or 0),
            confidence_failures=int(conf_row[1] or 0),
            confidence_samples=int(conf_row[0] or 0),
            sharp_reversals=int(sharp_row[1] or 0),
            sharp_samples=int(sharp_row[0] or 0),
        )
