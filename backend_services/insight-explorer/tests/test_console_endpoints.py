"""Endpoints the Console has been calling against thin air.

Three paths were wired in the Console UI but never existed server-side,
so four screens silently rendered a 404 as empty state:

  * GET  /explorer/data-intelligence/dashboard  (the whole Data
    Intelligence overview — data-intelligence-center, explorer-ops,
    operational-command-center, operations-center)
  * POST /explorer/sources/priority
  * POST /explorer/tickets/annotate

The dashboard's key set here is exactly what those components read; if a
key is renamed the Console silently shows zeros again, so it is asserted
explicitly rather than loosely.
"""

import json

import pytest

from explorer.api.service import ExplorerReadService
from explorer.ops import runtime_config
from explorer.ops.controls import ControlError, ExplorerControls
from explorer.tickets.tickets import TicketStore


def _service(tmp_path) -> ExplorerReadService:
    return ExplorerReadService(tmp_path)


def _write_jobs(tmp_path, rows):
    directory = tmp_path / "reports" / "jobs"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "jobs.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


# --- dashboard --------------------------------------------------------------


def test_dashboard_exposes_every_key_the_console_reads(tmp_path):
    dashboard = _service(tmp_path).data_intelligence_dashboard()
    for key in (
        "active_jobs", "failed_jobs", "retries",
        "throughput_records_per_second", "sources", "datasets",
        "records_per_source",
    ):
        assert key in dashboard, f"Console reads dashboard.{key}"


def test_dashboard_on_empty_lake_is_zeroed_not_broken(tmp_path):
    dashboard = _service(tmp_path).data_intelligence_dashboard()
    assert dashboard["active_jobs"] == 0
    assert dashboard["failed_jobs"] == 0
    assert dashboard["throughput_records_per_second"] == 0.0
    assert isinstance(dashboard["sources"], list)


def test_dashboard_counts_jobs_by_status(tmp_path):
    _write_jobs(tmp_path, [
        {"job_id": "a", "status": "running", "source": "espn"},
        {"job_id": "b", "status": "running", "source": "espn"},
        {"job_id": "c", "status": "failed", "source": "fbref"},
        {"job_id": "d", "status": "completed", "source": "espn",
         "records_validated": 100, "duration_ms": 2000},
    ])
    dashboard = _service(tmp_path).data_intelligence_dashboard()
    assert dashboard["active_jobs"] == 2
    assert dashboard["failed_jobs"] == 1
    # 100 validated records over 2s of collection time.
    assert dashboard["throughput_records_per_second"] == 50.0


def test_dashboard_never_divides_by_zero_duration(tmp_path):
    _write_jobs(tmp_path, [
        {"job_id": "a", "status": "completed", "source": "espn",
         "records_validated": 10, "duration_ms": 0},
    ])
    assert _service(tmp_path).data_intelligence_dashboard()[
        "throughput_records_per_second"
    ] == 0.0


def test_dashboard_records_per_source_is_keyed_by_source_name(tmp_path):
    _write_jobs(tmp_path, [
        {"job_id": "a", "status": "completed", "source": "espn",
         "records_validated": 40, "duration_ms": 1000},
    ])
    dashboard = _service(tmp_path).data_intelligence_dashboard()
    assert dashboard["records_per_source"]["espn"] == 40


# --- source priority --------------------------------------------------------


def test_set_source_priority_persists_and_surfaces_in_sources(tmp_path):
    controls = ExplorerControls(root=tmp_path)
    controls.set_source_priority("espn", 1, actor="operator")

    assert runtime_config.load(tmp_path).priority_for("espn") == 1
    espn = next(s for s in _service(tmp_path).sources() if s["name"] == "espn")
    assert espn["priority"] == 1


def test_source_priority_defaults_when_unset(tmp_path):
    espn = next(s for s in _service(tmp_path).sources() if s["name"] == "espn")
    assert espn["priority"] == 100


def test_set_source_priority_rejects_unknown_source(tmp_path):
    with pytest.raises(ControlError, match="unknown source"):
        ExplorerControls(root=tmp_path).set_source_priority("nope", 1)


def test_set_source_priority_rejects_non_integer_and_negative(tmp_path):
    controls = ExplorerControls(root=tmp_path)
    with pytest.raises(ControlError, match="integer"):
        controls.set_source_priority("espn", "high")
    with pytest.raises(ControlError, match=">= 0"):
        controls.set_source_priority("espn", -1)


def test_priority_survives_a_config_schema_change(tmp_path):
    """`runtime_config.load` drops unknown keys; adding source_priority
    must not disturb an existing on-disk config."""
    controls = ExplorerControls(root=tmp_path)
    controls.disable_source("espn")
    controls.set_source_priority("fbref", 5)
    cfg = runtime_config.load(tmp_path)
    assert cfg.disabled_sources == ["espn"]
    assert cfg.priority_for("fbref") == 5


# --- ticket annotation ------------------------------------------------------


def _open_ticket(tmp_path) -> str:
    store = TicketStore(tmp_path)
    ticket = store.open(
        error_type="source_offline", source="espn", competition="premier_league",
        season="2026", entity_type="fixture",
    )
    store.flush()
    return ticket.ticket_id


def test_annotate_ticket_merges_on_read(tmp_path):
    ticket_id = _open_ticket(tmp_path)
    ExplorerControls(root=tmp_path).annotate_ticket(
        ticket_id, assignment="ana", comment="checking the provider",
        execution_id="exec-1", actor="operator",
    )
    ticket = next(
        t for t in _service(tmp_path).tickets(status=None)
        if t["ticket_id"] == ticket_id
    )
    assert ticket["assignment"] == "ana"
    assert ticket["comment"] == "checking the provider"
    assert ticket["execution_id"] == "exec-1"
    assert ticket["annotated_by"] == "operator"


def test_annotation_does_not_destroy_the_ticket_fields(tmp_path):
    """Tickets are append-only; the annotation is a SEPARATE record and
    must not overwrite the ticket snapshot."""
    ticket_id = _open_ticket(tmp_path)
    ExplorerControls(root=tmp_path).annotate_ticket(ticket_id, comment="note")
    ticket = next(
        t for t in _service(tmp_path).tickets(status=None)
        if t["ticket_id"] == ticket_id
    )
    assert ticket["error_type"] == "source_offline"
    assert ticket["source"] == "espn"
    assert ticket["suggested_action"]


def test_annotation_can_close_a_ticket(tmp_path):
    ticket_id = _open_ticket(tmp_path)
    assert _service(tmp_path).tickets(status="open")
    ExplorerControls(root=tmp_path).annotate_ticket(ticket_id, status="resolved")
    assert _service(tmp_path).tickets(status="open") == []
    assert _service(tmp_path).tickets(status="resolved")


def test_latest_annotation_wins(tmp_path):
    ticket_id = _open_ticket(tmp_path)
    controls = ExplorerControls(root=tmp_path)
    controls.annotate_ticket(ticket_id, assignment="ana")
    controls.annotate_ticket(ticket_id, assignment="bruno")
    ticket = next(
        t for t in _service(tmp_path).tickets(status=None)
        if t["ticket_id"] == ticket_id
    )
    assert ticket["assignment"] == "bruno"


def test_annotate_unknown_ticket_raises_control_error(tmp_path):
    with pytest.raises(ControlError, match="not found"):
        ExplorerControls(root=tmp_path).annotate_ticket("does-not-exist")


def test_annotate_rejects_invalid_status(tmp_path):
    ticket_id = _open_ticket(tmp_path)
    with pytest.raises(ControlError, match="invalid ticket status"):
        ExplorerControls(root=tmp_path).annotate_ticket(ticket_id, status="bogus")


def test_annotation_for_unknown_ticket_id_is_ignored_on_read(tmp_path):
    """A stale annotation must not conjure a ticket that doesn't exist."""
    _open_ticket(tmp_path)
    directory = tmp_path / "reports" / "tickets" / "annotations"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "annotations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ticket_id": "ghost", "comment": "x"}) + "\n")
    assert len(_service(tmp_path).tickets(status=None)) == 1
