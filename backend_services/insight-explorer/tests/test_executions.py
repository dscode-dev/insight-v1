import pytest

from explorer.pipelines.executions.models import Execution
from explorer.pipelines.executions.store import ExecutionNotFound, ExecutionStore


def test_create_and_get_roundtrip(tmp_path):
    store = ExecutionStore(tmp_path)
    execution = store.create(Execution(pipeline_id="p1", pipeline_name="Brasileirão"))
    assert execution.created_at
    fetched = store.get(execution.execution_id)
    assert fetched.pipeline_id == "p1"
    assert fetched.state == "pending"


def test_list_filters_by_pipeline_id_and_state(tmp_path):
    store = ExecutionStore(tmp_path)
    store.create(Execution(pipeline_id="p1", state="running"))
    store.create(Execution(pipeline_id="p1", state="completed"))
    store.create(Execution(pipeline_id="p2", state="running"))
    assert len(store.list(pipeline_id="p1")) == 2
    assert len(store.list(state="running")) == 2
    assert len(store.list(pipeline_id="p1", state="running")) == 1


def test_update_merges_and_preserves_id(tmp_path):
    store = ExecutionStore(tmp_path)
    execution = store.create(Execution(pipeline_id="p1"))
    updated = store.update(execution.execution_id, state="running", progress=0.5)
    assert updated.execution_id == execution.execution_id
    assert updated.state == "running"
    assert updated.progress == 0.5


def test_get_unknown_execution_raises(tmp_path):
    store = ExecutionStore(tmp_path)
    with pytest.raises(ExecutionNotFound):
        store.get("does-not-exist")


def test_save_persists_mutated_in_memory_execution(tmp_path):
    store = ExecutionStore(tmp_path)
    execution = store.create(Execution(pipeline_id="p1"))
    execution.jobs_completed = 3
    execution.progress = 0.3
    store.save(execution)
    assert store.get(execution.execution_id).jobs_completed == 3
