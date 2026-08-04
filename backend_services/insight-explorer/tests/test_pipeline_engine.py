from __future__ import annotations

import time
from typing import Iterator

import pytest
from _helpers import FakeAdapter, sample_artifacts

from explorer.adapters.base import RawArtifact
from explorer.datalake.lake import DataLake
from explorer.pipelines.engine import ExecutionNotRunning, ExecutionSupervisor, decompose
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.models import Pipeline, PipelineSource
from explorer.pipelines.store import PipelineStore


class SlowFakeAdapter(FakeAdapter):
    """Same as FakeAdapter but sleeps briefly per fetch — gives pause/stop
    tests a real window to intervene mid-run, deterministically."""

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        time.sleep(0.05)
        yield from self._artifacts


def _wait_for(predicate, timeout: float = 5.0, interval: float = 0.01) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _recurring_pipeline() -> Pipeline:
    return Pipeline(
        name="Brasileirão enrichment", type="historical",
        sources=[PipelineSource("espn", enabled=True)],
        competitions=["brasileirao_serie_a"], themes=["fixtures"],
        duration={"mode": "recurring"},
    )


def test_decompose_empty_for_non_collectible_theme():
    pipeline = Pipeline(name="x", competitions=["brasileirao_serie_a"], themes=["odds"],
                        duration={"mode": "one-shot"})
    assert decompose(pipeline) == []


def test_decompose_builds_one_task_per_competition_season():
    pipeline = Pipeline(name="x", competitions=["brasileirao_serie_a"], themes=["fixtures"],
                        duration={"mode": "recurring"})
    tasks = decompose(pipeline)
    assert len(tasks) == 3
    assert all(t["competition"] == "brasileirao_serie_a" for t in tasks)


def _supervisor(tmp_path, adapter):
    lake = DataLake(tmp_path)
    pipeline_store = PipelineStore(tmp_path)
    execution_store = ExecutionStore(tmp_path)
    supervisor = ExecutionSupervisor(lake, pipeline_store, execution_store, use_ai=False,
                                     registry=[adapter])
    return supervisor, pipeline_store, execution_store


def test_supervisor_runs_execution_to_completion(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path, FakeAdapter(sample_artifacts()))
    pipeline = pipeline_store.create(_recurring_pipeline())
    execution = supervisor.start_execution(pipeline.pipeline_id)
    assert execution.jobs_total == 3

    assert _wait_for(lambda: execution_store.get(execution.execution_id).state == "completed")
    final = execution_store.get(execution.execution_id)
    assert final.jobs_completed == 3
    assert final.records == 6  # 2 validated records per task * 3 tasks
    assert final.progress == 1.0
    assert final.source_contribution.get("espn") == 6


def test_start_execution_rejects_realtime_pipeline(tmp_path):
    supervisor, pipeline_store, _ = _supervisor(tmp_path, FakeAdapter(sample_artifacts()))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime"))
    with pytest.raises(ValueError):
        supervisor.start_execution(pipeline.pipeline_id)


def test_pause_unknown_execution_raises(tmp_path):
    supervisor, _, _ = _supervisor(tmp_path, FakeAdapter(sample_artifacts()))
    with pytest.raises(ExecutionNotRunning):
        supervisor.pause("does-not-exist")


def test_supervisor_pause_then_resume_completes(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path, SlowFakeAdapter(sample_artifacts()))
    pipeline = pipeline_store.create(_recurring_pipeline())
    execution = supervisor.start_execution(pipeline.pipeline_id)

    supervisor.pause(execution.execution_id)
    assert _wait_for(lambda: execution_store.get(execution.execution_id).state == "paused")
    completed_at_pause = execution_store.get(execution.execution_id).jobs_completed
    time.sleep(0.3)  # would have advanced by now if pause weren't honored
    assert execution_store.get(execution.execution_id).jobs_completed == completed_at_pause
    assert execution_store.get(execution.execution_id).state == "paused"

    supervisor.resume(execution.execution_id)
    assert _wait_for(lambda: execution_store.get(execution.execution_id).state == "completed")
    assert execution_store.get(execution.execution_id).jobs_completed == 3


def test_supervisor_stop_halts_before_completion(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path, SlowFakeAdapter(sample_artifacts()))
    pipeline = pipeline_store.create(_recurring_pipeline())
    execution = supervisor.start_execution(pipeline.pipeline_id)

    supervisor.stop(execution.execution_id)
    assert _wait_for(lambda: execution_store.get(execution.execution_id).state == "stopped")
    final = execution_store.get(execution.execution_id)
    assert final.ended_at
    assert final.jobs_completed < final.jobs_total
