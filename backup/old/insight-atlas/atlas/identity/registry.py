"""Persistent identity registry (Postgres / SQLite).

The authoritative store for canonical matches + provider aliases. The
fuzzy time-window match is done in Python after a competition+teams
shortlist so the query stays portable across Postgres and the SQLite
used in tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.identity.models import CanonicalMatch
from atlas.registry.models import CanonicalMatchRow, MatchAliasRow


class IdentityRegistry:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def alias_lookup(self, provider: str, external_id: str) -> UUID | None:
        async with self._sf() as session:
            row = await session.get(MatchAliasRow, (provider, external_id))
            return row.canonical_match_id if row is not None else None

    async def find_within_tolerance(
        self,
        competition_id: UUID | None,
        norm_home: str,
        norm_away: str,
        kickoff: datetime,
        tolerance_seconds: int,
    ) -> CanonicalMatch | None:
        async with self._sf() as session:
            stmt = select(CanonicalMatchRow).where(
                CanonicalMatchRow.home_team == norm_home,
                CanonicalMatchRow.away_team == norm_away,
            )
            if competition_id is not None:
                stmt = stmt.where(CanonicalMatchRow.competition_id == competition_id)
            rows = (await session.execute(stmt)).scalars().all()
        target = _as_utc(kickoff)
        for row in rows:
            if row.kickoff is None:
                continue
            if abs((_as_utc(row.kickoff) - target).total_seconds()) <= tolerance_seconds:
                return _to_match(row)
        return None

    async def save(
        self,
        match: CanonicalMatch,
        *,
        provider: str,
        external_id: str,
        linked_by: str = "auto",
    ) -> None:
        async with self._sf() as session:
            existing = await session.get(CanonicalMatchRow, match.canonical_match_id)
            if existing is None:
                session.add(
                    CanonicalMatchRow(
                        canonical_match_id=match.canonical_match_id,
                        competition_id=match.competition_id,
                        home_team=match.home_team,
                        away_team=match.away_team,
                        kickoff=match.kickoff,
                    )
                )
            if provider and external_id:
                alias = await session.get(MatchAliasRow, (provider, external_id))
                if alias is None:
                    session.add(
                        MatchAliasRow(
                            provider=provider,
                            external_id=external_id,
                            canonical_match_id=match.canonical_match_id,
                            linked_by=linked_by,
                        )
                    )
            await session.commit()


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _to_match(row: CanonicalMatchRow) -> CanonicalMatch:
    return CanonicalMatch(
        canonical_match_id=row.canonical_match_id,
        competition_id=row.competition_id,
        home_team=row.home_team,
        away_team=row.away_team,
        kickoff=row.kickoff,
    )
