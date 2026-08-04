import json

from explorer.datalake.lake import DataLake
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.migration import DEFAULT_EXECUTION_ID, DEFAULT_PIPELINE_ID, seed_default_pipeline
from explorer.pipelines.store import PipelineStore
from explorer.scheduler import PLAN


def test_seed_creates_default_pipeline_and_execution(tmp_path):
    lake = DataLake(tmp_path)
    pipeline = seed_default_pipeline(lake)
    assert pipeline is not None
    assert pipeline.pipeline_id == DEFAULT_PIPELINE_ID
    assert pipeline.duration["mode"] == "recurring"

    execution = ExecutionStore(tmp_path).get(DEFAULT_EXECUTION_ID)
    assert execution.jobs_total == len(PLAN)
    assert execution.jobs_completed == 0
    assert execution.state == "pending"


def test_seed_is_idempotent(tmp_path):
    lake = DataLake(tmp_path)
    first = seed_default_pipeline(lake)
    second = seed_default_pipeline(lake)
    assert first is not None
    assert second is None
    assert len(PipelineStore(tmp_path).list()) == 1


def test_seed_marks_already_completed_tasks_from_legacy_scheduler_state(tmp_path):
    lake = DataLake(tmp_path)
    state_path = tmp_path / "reports" / "scheduler_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    completed = [list(PLAN[0]), list(PLAN[1])]
    state_path.write_text(json.dumps({"completed": completed}), "utf-8")

    seed_default_pipeline(lake)
    execution = ExecutionStore(tmp_path).get(DEFAULT_EXECUTION_ID)
    assert execution.jobs_completed == 2
    done_tasks = [(t["competition"], t["season"]) for t in execution.tasks if t["status"] == "done"]
    assert set(done_tasks) == {tuple(c) for c in completed}
