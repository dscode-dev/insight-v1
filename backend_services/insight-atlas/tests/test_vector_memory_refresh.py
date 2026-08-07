"""The refresh that keeps pgvector current with the Explorer's collection.

Both halves of this chain — build the corpus, encode it into pgvector —
existed as scripts nobody ran, and the vector memory stayed empty while
ClickHouse filled up. An empty vector table fails quietly: every query
succeeds, returns nothing, and Atlas reports low confidence rather than no
data. These tests cover the parts that decide whether it runs at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.vector_memory.refresh import (
    RefreshResult,
    VectorMemoryRefresher,
    lake_fingerprint,
)


def _lake(tmp_path: Path, records: int = 2) -> Path:
    lake = tmp_path / "validated" / "premier_league" / "2026" / "openfootball" / "fixture"
    lake.mkdir(parents=True)
    (lake / "part-0001.jsonl").write_text(
        "\n".join(json.dumps({"n": i}) for i in range(records)) + "\n",
        encoding="utf-8",
    )
    return tmp_path / "validated"


class _Recorder:
    """Stands in for the dataset build and the encoder."""

    def __init__(self, rows: int = 3, stats: dict | None = None):
        self.rows = rows
        self.stats = stats or {}
        self.builds = 0
        self.upserts: list[str] = []

    def build(self, lake_dir: str, out_dir: str) -> dict:
        self.builds += 1
        for name in ("matches.jsonl", "projection.jsonl"):
            (Path(out_dir) / name).write_text("{}\n", encoding="utf-8")
        return {"rows": self.rows, "read": self.rows, **self.stats}

    async def encode(self, matches: Path, projection: Path, version: str) -> int:
        assert matches.exists(), "build deve ter escrito matches.jsonl"
        self.upserts.append(version)
        return self.rows


class _Clock:
    """A hand-advanced monotonic clock.

    The refresher self-throttles at 30 minutes, so back-to-back calls in a
    test are indistinguishable from the production case it exists to
    prevent. Advancing time explicitly says which of the two each test means.
    """

    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds

    def advance(self, seconds: float) -> None:
        self.seconds += seconds


def _refresher(
    tmp_path: Path, recorder: _Recorder, clock: _Clock | None = None, **kwargs
) -> VectorMemoryRefresher:
    datasets = tmp_path / "datasets"
    datasets.mkdir(exist_ok=True)
    return VectorMemoryRefresher(
        lake_dir=_lake(tmp_path),
        dataset_dir=datasets,
        build=recorder.build,
        encode_and_upsert=recorder.encode,
        now=clock or _Clock(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_first_pass_builds_and_writes_every_version(tmp_path):
    recorder = _Recorder(rows=5)
    refresher = _refresher(tmp_path, recorder)

    result = await refresher.refresh()

    assert result.status == "written"
    assert result.rows == 5
    assert recorder.upserts == ["v1", "v2"], "as duas versoes sao lidas em runtime"
    assert (tmp_path / "datasets" / "current" / "matches.jsonl").exists()


@pytest.mark.asyncio
async def test_second_pass_skips_when_the_lake_has_not_changed(tmp_path):
    """A rebuild reads every record. Paying that when nothing was collected
    is the common case, so the fingerprint has to make it a directory walk."""
    recorder = _Recorder()
    refresher = _refresher(tmp_path, recorder)

    await refresher.refresh()
    second = await refresher.refresh()

    assert second.status == "unchanged"
    assert recorder.builds == 1


@pytest.mark.asyncio
async def test_new_collection_triggers_a_rebuild(tmp_path):
    recorder = _Recorder()
    clock = _Clock()
    refresher = _refresher(tmp_path, recorder, clock)
    await refresher.refresh()

    part = next((tmp_path / "validated").rglob("*.jsonl"))
    with part.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"n": 99}) + "\n")

    clock.advance(2000)
    assert (await refresher.refresh()).status == "written"
    assert recorder.builds == 2


@pytest.mark.asyncio
async def test_the_lake_is_not_walked_on_every_tick(tmp_path):
    """The watcher tick is 30s and the walk is an rglob over a lake that only
    grows. New data still waits at most one interval — collection runs on the
    order of hours, so the delay is not what bounds freshness."""
    recorder = _Recorder()
    clock = _Clock()
    refresher = _refresher(tmp_path, recorder, clock)
    await refresher.refresh()

    part = next((tmp_path / "validated").rglob("*.jsonl"))
    with part.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"n": 99}) + "\n")

    clock.advance(30)
    result = await refresher.refresh()

    assert result.status == "unchanged"
    assert result.detail == "throttled"
    assert recorder.builds == 1


@pytest.mark.asyncio
async def test_force_rebuilds_an_unchanged_lake(tmp_path):
    recorder = _Recorder()
    refresher = _refresher(tmp_path, recorder)
    await refresher.refresh()

    assert (await refresher.refresh(force=True)).status == "written"
    assert recorder.builds == 2


@pytest.mark.asyncio
async def test_a_failed_pass_does_not_record_the_lake_as_processed(tmp_path):
    """Advancing the fingerprint on failure would skip the retry, leaving the
    vector memory stale until the next collection happened to arrive."""
    recorder = _Recorder()
    clock = _Clock()
    refresher = _refresher(tmp_path, recorder, clock)

    def explode(lake_dir: str, out_dir: str) -> dict:
        recorder.builds += 1
        raise RuntimeError("clickhouse fora do ar")

    refresher.build = explode
    with pytest.raises(RuntimeError):
        await refresher.refresh()

    refresher.build = recorder.build
    clock.advance(2000)
    assert (await refresher.refresh()).status == "written"
    assert recorder.builds == 2


@pytest.mark.asyncio
async def test_an_empty_dataset_never_replaces_a_good_one(tmp_path):
    """A build that finds nothing must not publish. Overwriting a working
    corpus with an empty one turns a collection outage into a silent loss of
    every neighbour the live path reads."""
    recorder = _Recorder(rows=4)
    refresher = _refresher(tmp_path, recorder)
    await refresher.refresh()

    empty = _Recorder(rows=0)
    refresher.build = empty.build
    result = await refresher.refresh(force=True)

    assert result.status == "empty"
    assert empty.upserts == []
    assert (tmp_path / "datasets" / "current" / "matches.jsonl").exists()


@pytest.mark.asyncio
async def test_the_dedup_counters_reach_the_result(tmp_path):
    """`collapsed` is how the duplicate-match bug would have been visible
    before it corrupted every Elo rating in the corpus."""
    recorder = _Recorder(rows=1560, stats={
        "read": 2984, "collapsed": 1424, "multi_source": 1410,
        "score_conflicts": 0,
    })
    result = await _refresher(tmp_path, recorder).refresh()

    assert result.collapsed == 1424
    assert result.multi_source == 1410
    assert result.as_dict()["score_conflicts"] == 0


@pytest.mark.asyncio
async def test_disabled_refresher_does_nothing(tmp_path):
    recorder = _Recorder()
    refresher = _refresher(tmp_path, recorder, is_enabled=False)

    assert (await refresher.refresh()).status == "unchanged"
    assert recorder.builds == 0


def test_fingerprint_moves_with_size_and_mtime(tmp_path):
    lake = _lake(tmp_path)
    before = lake_fingerprint(lake)

    part = next(lake.rglob("*.jsonl"))
    with part.open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    assert lake_fingerprint(lake) != before


def test_fingerprint_of_an_absent_lake_is_not_an_error(tmp_path):
    """A deployment collecting nothing yet must skip, not crash the watcher."""
    assert lake_fingerprint(tmp_path / "nao-existe") == "absent"


def test_result_serialises_for_the_console():
    payload = RefreshResult(status="written", rows=7, versions=("v1",)).as_dict()
    assert payload["status"] == "written"
    assert payload["versions"] == ["v1"]
