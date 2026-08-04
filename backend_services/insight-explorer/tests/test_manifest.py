from _helpers import FakeAdapter, sample_artifacts

from explorer.datalake.lake import DataLake
from explorer.jobs.multi import run_multi_source
from explorer.jobs.runner import JobRunner
from explorer.pipelines.executions.models import Execution
from explorer.pipelines.manifest import build_dataset_view, build_manifest
from explorer.pipelines.models import Pipeline, PipelineSource


def _seeded_execution(tmp_path):
    lake = DataLake(tmp_path)
    runner = JobRunner(lake=lake, use_ai=False)
    run_multi_source("brasileirao_serie_a", "2022", runner=runner,
                     registry=[FakeAdapter(sample_artifacts())], execution_id="exec-1")
    pipeline = Pipeline(name="x", pipeline_id="p1", sources=[PipelineSource("espn")],
                        competitions=["brasileirao_serie_a"], themes=["fixtures"])
    execution = Execution(pipeline_id="p1", execution_id="exec-1",
                          tasks=[{"competition": "brasileirao_serie_a", "season": "2022", "status": "done"}])
    return lake, pipeline, execution


def test_build_manifest_counts_validated_records(tmp_path):
    lake, pipeline, execution = _seeded_execution(tmp_path)
    manifest = build_manifest(execution, pipeline, lake)
    assert manifest["totals"]["fixtures"] == 2
    assert manifest["partitions"] == [
        {"competition": "brasileirao_serie_a", "season": "2022", "source": "espn", "records": 2}]
    assert manifest["odds_coverage"]["percentage"] == 0.0
    assert manifest["checksum"].startswith("sha256:")


def test_build_manifest_no_data_yields_zero_totals(tmp_path):
    lake = DataLake(tmp_path)
    pipeline = Pipeline(name="x", pipeline_id="p1", sources=[PipelineSource("espn")])
    execution = Execution(pipeline_id="p1",
                          tasks=[{"competition": "brasileirao_serie_a", "season": "2099", "status": "done"}])
    manifest = build_manifest(execution, pipeline, lake)
    assert manifest["totals"]["fixtures"] == 0
    assert manifest["partitions"] == []


def test_dataset_view_wraps_manifest(tmp_path):
    lake, pipeline, execution = _seeded_execution(tmp_path)
    view = build_dataset_view(execution, pipeline, lake)
    assert view["generation"] == execution.execution_id
    assert view["checksum"] == view["manifest"]["checksum"]
    assert view["manifest"]["totals"]["fixtures"] == 2
