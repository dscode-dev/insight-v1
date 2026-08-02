from _helpers import FakeAdapter

from explorer.api.service import ExplorerReadService
from explorer.datalake.lake import DataLake
from explorer.jobs.runner import JobRunner
from explorer.observability.telemetry import Telemetry
from explorer.ops import runtime_config
from explorer.ops.controls import ExplorerControls


def _seed(tmp_path, sample_artifacts):
    lake = DataLake(tmp_path)
    runner = JobRunner(lake=lake, use_ai=False)
    runner.run(FakeAdapter(sample_artifacts), "brasileirao_serie_a", "2022")
    runner.tickets.flush()
    return ExplorerReadService(tmp_path)


def test_status_and_datasets(tmp_path, sample_artifacts):
    svc = _seed(tmp_path, sample_artifacts)
    status = svc.status()
    assert status["jobs_total"] >= 1
    assert status["records_validated"] == 2
    ds = svc.datasets()
    assert any(d["competition"] == "brasileirao_serie_a" and d["records"] == 2 for d in ds)
    detail = svc.dataset_detail("brasileirao_serie_a")
    assert detail["totals"]["validated"] == 2
    assert "2022" in detail["seasons"]


def test_sources_and_storage_and_quality(tmp_path, sample_artifacts):
    svc = _seed(tmp_path, sample_artifacts)
    sources = svc.sources()
    names = {s["name"] for s in sources}
    assert {"espn", "fbref", "football_data", "wikipedia"} <= names
    assert all("enabled" in s for s in sources)
    storage = svc.storage()
    assert storage["total_bytes"] > 0
    assert set(storage["layers_bytes"]) >= {"raw", "validated", "reports"}
    q = svc.quality()
    assert q["records_validated"] == 2
    assert q["validation_rate"] is not None


def test_agents_and_langgraph_from_telemetry(tmp_path):
    tel = Telemetry(tmp_path)
    tel.agent_call(agent="entity_resolver", backend="crewai", latency_s=1.2,
                   prompt_tokens=100, completion_tokens=20, success=True,
                   sample_input="resolve X", sample_output="{...}")
    tel.graph_run(run_id="r1", competition="libertadores", season="2022", source="espn",
                  engine="langgraph", nodes=["collect", "approve"], validated=10,
                  rejected=1, review=2, duration_s=3.0, outcome="completed")
    svc = ExplorerReadService(tmp_path)
    agents = svc.agents()
    er = next(a for a in agents["agents"] if a["agent"] == "entity_resolver")
    assert er["tasks_executed"] == 1
    assert er["success_rate"] == 1.0
    assert er["examples"]
    lg = svc.langgraph()
    assert lg["workflows_completed"] == 1
    assert lg["approval_rate"] is not None
    assert lg["latest_runs"]


def test_controls_audited(tmp_path):
    ctrl = ExplorerControls(scheduler=None, root=tmp_path)
    ctrl.disable_source("fbref", actor="tester")
    cfg = runtime_config.load(tmp_path)
    assert "fbref" in cfg.disabled_sources
    ctrl.enable_source("fbref", actor="tester")
    assert "fbref" not in runtime_config.load(tmp_path).disabled_sources
    audit = ExplorerReadService(tmp_path).audit_log()
    actions = {a["action"] for a in audit}
    assert {"sources.disable", "sources.enable"} <= actions


def test_disabled_source_skipped_in_multi(tmp_path, sample_artifacts):
    from explorer.jobs.multi import run_multi_source

    runtime_config.save(runtime_config.RuntimeConfig(disabled_sources=["espn"]), tmp_path)
    lake = DataLake(tmp_path)
    runner = JobRunner(lake=lake, use_ai=False)
    result = run_multi_source("brasileirao_serie_a", "2022", runner=runner,
                              registry=[FakeAdapter(sample_artifacts)])
    assert "espn" not in result["sources_run"]  # disabled → not run


def test_scheduler_pause_resume_via_config(tmp_path):
    from explorer.scheduler import Scheduler

    sched = Scheduler(lake=DataLake(tmp_path), use_ai=False, plan=(("brasileirao_serie_a", "2020"),))
    sched.pause()
    assert runtime_config.load(tmp_path).scheduler_paused is True
    sched.resume()
    assert runtime_config.load(tmp_path).scheduler_paused is False


def test_scheduler_enqueue_priority(tmp_path):
    from explorer.scheduler import Scheduler

    sched = Scheduler(lake=DataLake(tmp_path), use_ai=False, plan=())
    sched.enqueue("libertadores", "2022")
    assert sched._next_task() == ("libertadores", "2022")
