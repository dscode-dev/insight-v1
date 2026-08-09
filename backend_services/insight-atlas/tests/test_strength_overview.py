"""Operational visibility for the live team-strength engine (ATLAS-SIM-A).

The engine, its four state tables and the Explorer sync watcher shipped
with no way to answer "is this populated, and when did it last sync?".
A cold engine is indistinguishable from a warm one through any per-match
lookup — a seeded team returns a perfectly plausible 1500 — while the
similarity signals that depend on it quietly run on defaults.

Does NOT import `atlas.api.*`: `atlas/operations.py` pulls in the
POSIX-only `resource` module, which breaks collection of the whole suite
on Windows. The route is a thin wrapper over `overview()`.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

import pytest

from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.strength.models import MatchResult
from atlas.strength.repository import StrengthRepository


@pytest.fixture
async def strength():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None  # sqlite has no `atlas` schema
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield StrengthRepository(build_session_factory(engine))
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _match(home: str, away: str, uid: str, *, hg: int = 2, ag: int = 0) -> MatchResult:
    return MatchResult(
        uid=uid,
        competition="brasileirao",
        season="2025",
        kickoff_at=datetime(2025, 5, 1, 20, 0, tzinfo=timezone.utc),
        home=home,
        away=away,
        home_score=hg,
        away_score=ag,
    )


@pytest.mark.asyncio
class TestOverview:
    async def test_reports_an_empty_engine_honestly(self, strength):
        overview = await strength.overview()

        # The cold case must read as cold, not as a healthy zero.
        assert overview["teams_tracked"] == 0
        assert overview["matches_processed"] == 0
        assert overview["last_sync_at"] is None
        assert overview["top_by_elo"] == []

    async def test_counts_state_after_a_result(self, strength):
        await strength.record_result(_match("flamengo", "vasco", "m1"))

        overview = await strength.overview()

        assert overview["teams_tracked"] == 2
        assert overview["matches_processed"] == 1
        assert overview["head_to_head_pairs"] == 1
        assert overview["standings_rows"] == 2
        assert overview["last_sync_at"] is not None

    async def test_reports_zero_spread_before_anything_is_recorded(self, strength):
        # Spread is what answers "has the engine told anybody apart".
        # Counting teams still at exactly 1500.0 does NOT: every team in
        # the table arrived through a result, and HOME_ADVANTAGE makes
        # even a draw an under-performance for the home side, so that
        # count is a float equality that is almost always zero — it
        # would read as "fully warmed up" for a one-match engine.
        overview = await strength.overview()

        assert overview["elo_spread"] == 0.0
        assert overview["elo_min"] is None
        assert overview["elo_max"] is None

    async def test_spread_opens_once_results_differentiate_teams(self, strength):
        await strength.record_result(_match("winner", "loser", "m1", hg=5, ag=0))

        overview = await strength.overview()

        assert overview["elo_spread"] > 0
        assert overview["elo_max"] > overview["elo_min"]

    async def test_a_draw_still_moves_ratings(self, strength):
        # Documents the real behaviour rather than the intuitive one: a
        # draw is not neutral, because the home side was expected to win.
        await strength.record_result(_match("santos", "palmeiras", "m2", hg=1, ag=1))

        overview = await strength.overview()

        assert overview["elo_spread"] > 0

    async def test_ranks_by_elo_descending(self, strength):
        await strength.record_result(_match("winner", "loser", "m1", hg=5, ag=0))

        overview = await strength.overview()

        teams = [row["team"] for row in overview["top_by_elo"]]
        assert teams == ["winner", "loser"]
        assert overview["top_by_elo"][0]["elo"] > overview["top_by_elo"][1]["elo"]

    async def test_timestamps_are_timezone_aware_iso(self, strength):
        # sqlite hands back naive datetimes and postgres does not; a
        # naive string here would be read as local time by the console.
        await strength.record_result(_match("a", "b", "m1"))

        overview = await strength.overview()

        parsed = datetime.fromisoformat(overview["last_sync_at"])
        assert parsed.tzinfo is not None

    async def test_stays_consistent_across_repeated_results(self, strength):
        await strength.record_result(_match("a", "b", "m1"))
        # record_result is idempotent on match_uid — the overview must
        # not double-count a redelivered match.
        await strength.record_result(_match("a", "b", "m1"))

        overview = await strength.overview()

        assert overview["matches_processed"] == 1
        assert overview["teams_tracked"] == 2
