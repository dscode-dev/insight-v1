"""Regression coverage for ExplorerControls' pipeline/execution/realtime
methods — specifically that engine-level ValueErrors (wrong pipeline type)
are translated into ControlError, not left to propagate as a raw 500."""

import pytest
from _helpers import FakeAdapter, sample_artifacts

from explorer.datalake.lake import DataLake
from explorer.ops.controls import ControlError, ExplorerControls
from explorer.pipelines.engine import ExecutionSupervisor
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.models import Pipeline
from explorer.pipelines.store import PipelineStore
from explorer.realtime.collector import RealtimeCollector
from explorer.realtime.store import SignalSourceStore


def _controls(tmp_path):
    lake = DataLake(tmp_path)
    pipeline_store = PipelineStore(tmp_path)
    execution_store = ExecutionStore(tmp_path)
    supervisor = ExecutionSupervisor(lake, pipeline_store, execution_store, use_ai=False,
                                     registry=[FakeAdapter(sample_artifacts())])
    collector = RealtimeCollector(lake, pipeline_store, SignalSourceStore(tmp_path))
    controls = ExplorerControls(root=tmp_path, supervisor=supervisor, collector=collector)
    return controls, pipeline_store


def test_pipeline_execute_on_realtime_pipeline_raises_control_error_not_value_error(tmp_path):
    controls, pipeline_store = _controls(tmp_path)
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime"))
    with pytest.raises(ControlError):
        controls.pipeline_execute(pipeline.pipeline_id)


def test_pipeline_start_on_historical_pipeline_raises_control_error_not_value_error(tmp_path):
    controls, pipeline_store = _controls(tmp_path)
    pipeline = pipeline_store.create(Pipeline(name="x", type="historical"))
    with pytest.raises(ControlError):
        controls.pipeline_start(pipeline.pipeline_id)


def test_pipeline_execute_on_unknown_pipeline_raises_control_error(tmp_path):
    controls, _ = _controls(tmp_path)
    with pytest.raises(ControlError):
        controls.pipeline_execute("does-not-exist")
