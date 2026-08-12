"""StrengthRepository coverage — persistence, idempotency, and the
read-side feature computation the live similarity engine consumes.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import atlas.registry.models  # noqa: F401
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.strength import MatchResult, StrengthRepository


@pytest.fixture
async def repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield StrengthRepository(sf)
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _result(uid, home, away, home_score, away_score, *, kickoff_at, competition="premier_league", season="2026"):
    return MatchResult(
        uid=uid, competition=competition, season=season, kickoff_at=kickoff_at,
        home=home, away=away, home_score=home_score, away_score=away_score,
    )


@pytest.mark.asyncio
async def test_record_result_is_idempotent(repo):
    kickoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = _result("m1", "arsenal", "chelsea", 2, 0, kickoff_at=kickoff)
    assert await repo.record_result(result) is True
    assert await repo.record_result(result) is False  # duplicate, no-op


@pytest.mark.asyncio
async def test_features_for_match_cold_start_is_neutral(repo):
    features = await repo.features_for_match(
        competition="premier_league", season="2026",
        home="arsenal", away="chelsea", as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert features.elo_delta == 0.0
    assert features.home_attack_strength == 0.5
    assert features.away_attack_strength == 0.5
    assert features.h2h_advantage is None
    assert features.table_position_gap is None
    assert features.rest_advantage is None


@pytest.mark.asyncio
async def test_features_for_match_reflects_recorded_results(repo):
    kickoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Arsenal beats Chelsea twice — should show a positive elo_delta and
    # a positive h2h_advantage for Arsenal at home.
    await repo.record_result(_result("m1", "arsenal", "chelsea", 3, 0, kickoff_at=kickoff))
    await repo.record_result(
        _result("m2", "arsenal", "chelsea", 2, 1, kickoff_at=kickoff + timedelta(days=90))
    )
    features = await repo.features_for_match(
        competition="premier_league", season="2026",
        home="arsenal", away="chelsea",
        as_of=kickoff + timedelta(days=97),
    )
    assert features.elo_delta > 0.0
    assert features.h2h_advantage == 1.0  # 2 wins, 0 losses, 0 draws
    # Symmetric lookup: Chelsea at home vs Arsenal should show the
    # mirrored (negative) h2h_advantage.
    reversed_features = await repo.features_for_match(
        competition="premier_league", season="2026",
        home="chelsea", away="arsenal",
        as_of=kickoff + timedelta(days=97),
    )
    assert reversed_features.h2h_advantage == -1.0
    assert reversed_features.elo_delta < 0.0


@pytest.mark.asyncio
async def test_features_for_match_rest_advantage(repo):
    kickoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Arsenal played recently (3 days ago); Chelsea has no recorded
    # match at all yet -> rest_advantage stays None (one side unknown).
    await repo.record_result(_result("m1", "arsenal", "wolves", 1, 0, kickoff_at=kickoff))
    features = await repo.features_for_match(
        competition="premier_league", season="2026",
        home="arsenal", away="chelsea",
        as_of=kickoff + timedelta(days=3),
    )
    assert features.rest_advantage is None


@pytest.mark.asyncio
async def test_features_for_match_table_position_gap(repo):
    kickoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Arsenal wins 3 in a row (9 pts); Chelsea loses 3 in a row (0 pts) against
    # filler opponents -> Arsenal should rank above Chelsea.
    for i, opponent in enumerate(["wolves", "burnley", "everton"]):
        await repo.record_result(
            _result(f"a{i}", "arsenal", opponent, 2, 0, kickoff_at=kickoff + timedelta(days=i))
        )
        await repo.record_result(
            _result(f"c{i}", "chelsea", opponent, 0, 2, kickoff_at=kickoff + timedelta(days=i))
        )
    features = await repo.features_for_match(
        competition="premier_league", season="2026",
        home="arsenal", away="chelsea",
        as_of=kickoff + timedelta(days=10),
    )
    assert features.table_position_gap is not None
    assert features.table_position_gap > 0  # favors home (Arsenal, better position)
