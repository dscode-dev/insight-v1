"""StrengthRepository — persistence + read-side computation for the live
team-strength engine.

Backed by the same async SQLAlchemy session factory the model registry
and OddsRepository use (Postgres in production, SQLite in tests).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.registry.models import (
    CompetitionSeasonStateRow,
    HeadToHeadStateRow,
    StrengthProcessedMatchRow,
    TeamStandingsStateRow,
    TeamStrengthStateRow,
)
from atlas.strength import formulas as f
from atlas.strength.models import MatchResult, TeamStrengthFeatures

logger = logging.getLogger(__name__)


class StrengthRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def record_result(self, result: MatchResult) -> bool:
        """Fold one finished match into every derived state table.
        Idempotent on `result.uid` — a re-delivered/re-replayed match is
        a no-op. Returns True when newly applied, False when already
        processed.
        """
        async with self._sf() as session:
            if await session.get(StrengthProcessedMatchRow, result.uid) is not None:
                return False

            home_row = await session.get(TeamStrengthStateRow, result.home)
            if home_row is None:
                home_row = _new_team_strength_row(result.home)
                session.add(home_row)
            away_row = await session.get(TeamStrengthStateRow, result.away)
            if away_row is None:
                away_row = _new_team_strength_row(result.away)
                session.add(away_row)

            new_home_elo, new_away_elo = f.update_elo(
                home_row.elo, away_row.elo, result.home_score, result.away_score
            )
            new_venue_home, new_venue_away = f.update_venue_elo(
                home_row.venue_elo_home, away_row.venue_elo_away,
                result.home_score, result.away_score,
            )
            home_row.elo = new_home_elo
            away_row.elo = new_away_elo
            home_row.venue_elo_home = new_venue_home
            away_row.venue_elo_away = new_venue_away
            home_row.rolling_window = f.push_rolling_result(
                list(home_row.rolling_window or []), result.home_score, result.away_score
            )
            away_row.rolling_window = f.push_rolling_result(
                list(away_row.rolling_window or []), result.away_score, result.home_score
            )
            home_row.last_match_at = result.kickoff_at
            away_row.last_match_at = result.kickoff_at
            home_row.updated_at = _utcnow()
            away_row.updated_at = _utcnow()

            await self._apply_standings(session, result)
            await self._apply_competition_season(session, result)
            await self._apply_head_to_head(session, result)

            session.add(StrengthProcessedMatchRow(match_uid=result.uid))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.info(
                    "strength_result_duplicate_skipped", extra={"match_uid": result.uid}
                )
                return False
            return True

    async def _latest_season(self, session: AsyncSession, competition: str) -> str | None:
        stmt = (
            select(CompetitionSeasonStateRow.season)
            .where(CompetitionSeasonStateRow.competition == competition)
            .order_by(CompetitionSeasonStateRow.updated_at.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

    async def _apply_standings(self, session: AsyncSession, result: MatchResult) -> None:
        home_points = 3 if result.home_score > result.away_score else 1 if result.home_score == result.away_score else 0
        away_points = 3 if result.away_score > result.home_score else 1 if result.away_score == result.home_score else 0
        home = await session.get(
            TeamStandingsStateRow, (result.competition, result.season, result.home)
        )
        if home is None:
            home = TeamStandingsStateRow(
                competition=result.competition, season=result.season, team=result.home,
                points=0, goal_difference=0, matches_played=0,
            )
            session.add(home)
        away = await session.get(
            TeamStandingsStateRow, (result.competition, result.season, result.away)
        )
        if away is None:
            away = TeamStandingsStateRow(
                competition=result.competition, season=result.season, team=result.away,
                points=0, goal_difference=0, matches_played=0,
            )
            session.add(away)
        home.points += home_points
        home.goal_difference += result.home_score - result.away_score
        home.matches_played += 1
        home.updated_at = _utcnow()
        away.points += away_points
        away.goal_difference += result.away_score - result.home_score
        away.matches_played += 1
        away.updated_at = _utcnow()

    async def _apply_competition_season(self, session: AsyncSession, result: MatchResult) -> None:
        row = await session.get(
            CompetitionSeasonStateRow, (result.competition, result.season)
        )
        if row is None:
            row = CompetitionSeasonStateRow(
                competition=result.competition, season=result.season,
                goal_sum=0, team_match_count=0,
            )
            session.add(row)
        row.goal_sum += result.home_score + result.away_score
        row.team_match_count += 2
        row.updated_at = _utcnow()

    async def _apply_head_to_head(self, session: AsyncSession, result: MatchResult) -> None:
        team_a, team_b = sorted((result.home, result.away))
        row = await session.get(HeadToHeadStateRow, (team_a, team_b))
        if row is None:
            row = HeadToHeadStateRow(
                team_a=team_a, team_b=team_b, team_a_wins=0, team_b_wins=0, draws=0,
            )
            session.add(row)
        if result.home_score == result.away_score:
            row.draws += 1
        else:
            winner = result.home if result.home_score > result.away_score else result.away
            if winner == team_a:
                row.team_a_wins += 1
            else:
                row.team_b_wins += 1
        row.updated_at = _utcnow()

    async def features_for_match(
        self,
        *,
        competition: str,
        home: str,
        away: str,
        as_of: datetime,
        season: str | None = None,
    ) -> TeamStrengthFeatures:
        """Pure read: current state for both teams, no mutation.
        Missing history degrades gracefully — new teams get neutral Elo
        (elo_delta=0) and average strength (0.5); missing h2h/standings/
        rest all resolve to None per `TeamStrengthFeatures`'s contract.

        `season` is optional — live runtime requests don't carry a
        season field. When omitted, the most recently updated season on
        record for this competition is used (auto-detected "current
        season"); with no standings recorded at all yet,
        `table_position_gap` simply stays None.
        """
        async with self._sf() as session:
            home_row = await session.get(TeamStrengthStateRow, home)
            away_row = await session.get(TeamStrengthStateRow, away)
            home_elo = home_row.elo if home_row else f.DEFAULT_ELO
            away_elo = away_row.elo if away_row else f.DEFAULT_ELO

            if season is None:
                season = await self._latest_season(session, competition)

            comp_season = (
                await session.get(CompetitionSeasonStateRow, (competition, season))
                if season is not None else None
            )
            league_rate = f.goal_rate_from_totals(
                comp_season.goal_sum if comp_season else 0,
                comp_season.team_match_count if comp_season else 0,
            )

            home_window = list(home_row.rolling_window or []) if home_row else []
            away_window = list(away_row.rolling_window or []) if away_row else []

            team_a, team_b = sorted((home, away))
            h2h_row = await session.get(HeadToHeadStateRow, (team_a, team_b))
            if h2h_row is None:
                h2h_adv = None
            elif home == team_a:
                h2h_adv = f.h2h_advantage(h2h_row.team_a_wins, h2h_row.team_b_wins, h2h_row.draws)
            else:
                h2h_adv = f.h2h_advantage(h2h_row.team_b_wins, h2h_row.team_a_wins, h2h_row.draws)

            if season is not None:
                standings_stmt = (
                    select(TeamStandingsStateRow)
                    .where(
                        TeamStandingsStateRow.competition == competition,
                        TeamStandingsStateRow.season == season,
                    )
                    .order_by(
                        TeamStandingsStateRow.points.desc(),
                        TeamStandingsStateRow.goal_difference.desc(),
                    )
                )
                standings = (await session.execute(standings_stmt)).scalars().all()
            else:
                standings = []
            positions = {row.team: idx + 1 for idx, row in enumerate(standings)}
            position_gap = f.table_position_gap(
                positions.get(home), positions.get(away),
                league_size=max(len(standings), 2),
            )

            rest_home = f.rest_days(home_row.last_match_at, as_of) if home_row else None
            rest_away = f.rest_days(away_row.last_match_at, as_of) if away_row else None
            rest_adv = f.rest_advantage(rest_home, rest_away)

            return TeamStrengthFeatures(
                elo_delta=f.elo_delta_unit(home_elo, away_elo),
                home_attack_strength=f.unit_strength_ratio(f.attack_strength(home_window, league_rate)),
                away_attack_strength=f.unit_strength_ratio(f.attack_strength(away_window, league_rate)),
                home_defense_strength=f.unit_strength_ratio(f.defense_strength(home_window, league_rate)),
                away_defense_strength=f.unit_strength_ratio(f.defense_strength(away_window, league_rate)),
                h2h_advantage=h2h_adv,
                table_position_gap=position_gap,
                rest_advantage=rest_adv,
            )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_team_strength_row(team: str) -> TeamStrengthStateRow:
    # Explicit defaults, not the ORM column `default=` — that only
    # applies at flush time, and this row's fields are read (elo delta,
    # rolling window) in the same transaction before any flush happens.
    return TeamStrengthStateRow(
        team=team,
        elo=f.DEFAULT_ELO,
        venue_elo_home=f.DEFAULT_ELO,
        venue_elo_away=f.DEFAULT_ELO,
        rolling_window=[],
        last_match_at=None,
    )
