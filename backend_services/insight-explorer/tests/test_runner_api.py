from _helpers import FakeAdapter

from explorer.api.service import ExplorerReadService
from explorer.datalake.lake import DataLake
from explorer.jobs.runner import JobRunner
from explorer.tickets.tickets import TicketStore


def _runner(tmp_path, **kw):
    lake = DataLake(tmp_path)
    tickets = TicketStore(tmp_path)
    return JobRunner(lake=lake, tickets=tickets, use_ai=False, **kw)


def test_job_completes_and_populates_lake(tmp_path, sample_artifacts):
    runner = _runner(tmp_path)
    rec = runner.run(FakeAdapter(sample_artifacts), "brasileirao_serie_a", "2022")
    assert rec.status == "completed"
    assert rec.records_collected == 2
    assert rec.records_validated == 2
    # raw + validated layers written
    assert list(runner.lake.read("raw", "brasileirao_serie_a", "2022", "espn", "fixture"))
    assert list(runner.lake.read("validated", "brasileirao_serie_a", "2022", "espn", "fixture"))
    # job record persisted
    assert (tmp_path / "reports" / "jobs" / "jobs.jsonl").exists()


def test_offline_source_fails_with_ticket(tmp_path, sample_artifacts):
    runner = _runner(tmp_path)
    rec = runner.run(FakeAdapter(sample_artifacts, healthy=False), "brasileirao_serie_a", "2022")
    assert rec.status == "failed"
    assert any(t.error_type == "source_offline" for t in runner.tickets.all())


def test_unsupported_competition_skipped(tmp_path, sample_artifacts):
    runner = _runner(tmp_path)
    rec = runner.run(FakeAdapter(sample_artifacts), "la_liga", "2022")
    assert rec.status == "skipped"


def test_read_service_exposes_jobs_and_tickets(tmp_path, sample_artifacts):
    runner = _runner(tmp_path)
    rec = runner.run(FakeAdapter(sample_artifacts), "brasileirao_serie_a", "2022")
    runner.tickets.open(error_type="source_offline", source="espn",
                        competition="brasileirao_serie_a", season="2099", entity_type="fixture")
    runner.tickets.flush()

    svc = ExplorerReadService(tmp_path)
    jobs = svc.jobs(competition="brasileirao_serie_a")
    assert any(j["job_id"] == rec.job_id for j in jobs)
    assert svc.job(rec.job_id) is not None
    assert any(t["error_type"] == "source_offline" for t in svc.tickets(status="open"))
