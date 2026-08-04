import time

from _helpers import FakeAdapter, sample_artifacts

from explorer.datalake.lake import DataLake
from explorer.pipelines.engine import ExecutionSupervisor, RecurringDispatcher
from explorer.pipelines.executions.models import Execution
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.models import Pipeline, PipelineSource
from explorer.pipelines.store import PipelineStore


def _supervisor(tmp_path):
    lake = DataLake(tmp_path)
    pipeline_store = PipelineStore(tmp_path)
    execution_store = ExecutionStore(tmp_path)
    supervisor = ExecutionSupervisor(lake, pipeline_store, execution_store, use_ai=False,
                                     registry=[FakeAdapter(sample_artifacts())])
    return supervisor, pipeline_store, execution_store


def _wait_for(predicate, timeout=5.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _recurring_pipeline(pipeline_store) -> Pipeline:
    return pipeline_store.create(Pipeline(
        name="x", enabled=True, sources=[PipelineSource("espn")],
        competitions=["brasileirao_serie_a"], themes=["fixtures"], duration={"mode": "recurring"}))


def test_tick_starts_recurring_pipeline_with_no_active_execution(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path)
    pipeline = _recurring_pipeline(pipeline_store)
    dispatcher = RecurringDispatcher(supervisor)
    dispatcher._tick()
    assert _wait_for(lambda: len(execution_store.list(pipeline_id=pipeline.pipeline_id)) == 1)
    executions = execution_store.list(pipeline_id=pipeline.pipeline_id)
    assert _wait_for(lambda: execution_store.get(executions[0].execution_id).state == "completed")


def test_tick_skips_pipeline_with_execution_already_pending_or_running(tmp_path):
    """Unit-level: seeds an in-flight Execution directly (no real worker
    thread) so the dispatcher's skip decision is tested in isolation, not
    racing real background collection timing."""
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path)
    pipeline = _recurring_pipeline(pipeline_store)
    execution_store.create(Execution(pipeline_id=pipeline.pipeline_id, state="running"))

    dispatcher = RecurringDispatcher(supervisor)
    dispatcher._tick()
    dispatcher._tick()
    assert len(execution_store.list(pipeline_id=pipeline.pipeline_id)) == 1


def test_tick_starts_a_new_execution_once_the_previous_one_finished(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path)
    pipeline = _recurring_pipeline(pipeline_store)
    execution_store.create(Execution(pipeline_id=pipeline.pipeline_id, state="completed"))

    dispatcher = RecurringDispatcher(supervisor)
    dispatcher._tick()
    assert _wait_for(lambda: len(execution_store.list(pipeline_id=pipeline.pipeline_id)) == 2)
    new_execution = next(e for e in execution_store.list(pipeline_id=pipeline.pipeline_id) if e.jobs_total)
    assert _wait_for(lambda: execution_store.get(new_execution.execution_id).state == "completed")


def test_tick_ignores_disabled_and_non_recurring_pipelines(tmp_path):
    supervisor, pipeline_store, execution_store = _supervisor(tmp_path)
    pipeline_store.create(Pipeline(name="disabled", enabled=False, duration={"mode": "recurring"}))
    pipeline_store.create(Pipeline(name="one-shot", enabled=True, duration={"mode": "one-shot"}))
    dispatcher = RecurringDispatcher(supervisor)
    dispatcher._tick()
    assert execution_store.list() == []
