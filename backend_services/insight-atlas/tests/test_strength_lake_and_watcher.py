"""Coverage for atlas/strength/lake.py (Explorer lake parsing) and
atlas/strength/sync_watcher.py (throttled periodic sync)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

import atlas.registry.models  # noqa: F401
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.strength import StrengthRepository
from atlas.strength.lake import iter_match_results
from atlas.strength.sync_watcher import StrengthSyncWatcher


def _fixture_line(*, external_id, home, away, home_score, away_score, scheduled_at, status="finished", competition="premier_league", season="2026"):
    return json.dumps({
        "external_id": external_id,
        "season": season,
        "competition": {"competition_key": competition},
        "payload": {
            "status": status,
            "score": {"home": home_score, "away": away_score},
            "home_team": {"club_id": home},
            "away_team": {"club_id": away},
            "scheduled_at": scheduled_at,
        },
    })


@pytest.fixture
def lake_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def _write(lake_dir, filename, lines):
    path = os.path.join(lake_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def test_iter_match_results_sorted_chronologically_across_files(lake_dir):
    # Deliberately write the LATER match to the file that sorts first
    # alphabetically, to prove ordering comes from kickoff_at, not disk order.
    _write(lake_dir, "a_file.jsonl", [
        _fixture_line(external_id="e2", home="arsenal", away="chelsea", home_score=2, away_score=1, scheduled_at="2026-03-01T15:00:00Z"),
    ])
    _write(lake_dir, "b_file.jsonl", [
        _fixture_line(external_id="e1", home="wolves", away="burnley", home_score=1, away_score=0, scheduled_at="2026-01-01T15:00:00Z"),
    ])
    results = iter_match_results(lake_dir)
    assert [r.home for r in results] == ["wolves", "arsenal"]


def test_iter_match_results_skips_unfinished_and_incomplete(lake_dir):
    _write(lake_dir, "f.jsonl", [
        _fixture_line(external_id="e1", home="a", away="b", home_score=1, away_score=0, scheduled_at="2026-01-01T15:00:00Z", status="scheduled"),
        json.dumps({"external_id": "e2", "payload": {"status": "finished", "score": {"home": None, "away": 1}}}),
        "",  # blank line
    ])
    assert iter_match_results(lake_dir) == []


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


@pytest.mark.asyncio
async def test_watcher_sync_applies_new_results_and_is_idempotent(repo, lake_dir):
    _write(lake_dir, "f.jsonl", [
        _fixture_line(external_id="e1", home="arsenal", away="chelsea", home_score=2, away_score=1, scheduled_at="2026-01-01T15:00:00Z"),
    ])
    watcher = StrengthSyncWatcher(repo, lake_dir, min_sync_interval_seconds=0)
    applied_first = await watcher.sync(force=True)
    applied_second = await watcher.sync(force=True)
    assert applied_first == 1
    assert applied_second == 0  # already processed, idempotent


@pytest.mark.asyncio
async def test_watcher_throttles_without_force(repo, lake_dir):
    _write(lake_dir, "f.jsonl", [
        _fixture_line(external_id="e1", home="arsenal", away="chelsea", home_score=2, away_score=1, scheduled_at="2026-01-01T15:00:00Z"),
    ])
    clock = {"now": datetime(2026, 1, 1, tzinfo=timezone.utc)}
    watcher = StrengthSyncWatcher(
        repo, lake_dir, min_sync_interval_seconds=1800.0, now=lambda: clock["now"],
    )
    assert await watcher.sync() == 1
    # New result appears, but we're still within the throttle window.
    _write(lake_dir, "g.jsonl", [
        _fixture_line(external_id="e2", home="wolves", away="burnley", home_score=1, away_score=0, scheduled_at="2026-01-02T15:00:00Z"),
    ])
    clock["now"] += timedelta(seconds=60)
    assert await watcher.sync() == 0  # throttled, not yet due
    clock["now"] += timedelta(seconds=1800)
    assert await watcher.sync() == 1  # due now, picks up the new result


@pytest.mark.asyncio
async def test_watcher_observe_returns_no_observations(repo, lake_dir):
    watcher = StrengthSyncWatcher(repo, lake_dir, min_sync_interval_seconds=0)
    assert await watcher.observe() == []
