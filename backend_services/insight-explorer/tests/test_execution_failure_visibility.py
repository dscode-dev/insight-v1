"""A crashed execution must say so.

THE INCIDENT. Two historical executions ran for eleven hours showing
"running, 0/5 jobs, 0 records" in the console. Nothing was running: the
worker threads had died seconds after starting, on a `KeyError` in the
quality pipeline. `_run_bounded` wrapped the worker in try/finally with no
`except`, so the exception left the thread, the semaphore was released, and
the execution row on disk kept the last state anyone had written — "running".

A thread dump was what settled it: the process had a uvicorn main thread, a
dispatcher, a gRPC server and an OTel worker, and no execution thread at all.

Two failures, and the second is the one that cost the eleven hours:

  1. The quality pipeline assumed every payload was a fixture. It was, until
     odds and stats became collectible.
  2. A dead worker was indistinguishable from a working one.
"""

from __future__ import annotations

import threading

import pytest

from explorer.ai.pipeline import QualityPipeline
from explorer.pipelines.executions.models import Execution
from explorer.validators.quality import score


# --- 1. the quality pipeline must survive non-fixture payloads -------------

def _envelope(entity_type: str, payload: dict) -> dict:
    return {
        "schema_version": "explorer.envelope.v1",
        "source": "football_data",
        "entity_type": entity_type,
        "external_id": "x-1",
        "trust_level": "high",
        "payload": payload,
    }


class _RunState:
    """Minimal stand-in for the pipeline's RunState."""

    def __init__(self) -> None:
        self.normalized: list[dict] = []
        self.competition = "premier_league"
        self.season = "2023-2024"
        self.source = "football_data"


class _NullTickets:
    class _Dir:
        parent = type("P", (), {"parent": "/tmp"})()

    dir = _Dir()

    def open(self, **_kw):  # noqa: ANN003
        return None


def test_entity_resolution_survives_stats_and_odds_payloads():
    """The exact crash: `p["home_team"]` on a payload that has no clubs.

    A stats payload is {external_fixture_id, home, away} where home/away are
    counter objects; an odds payload names a bookmaker and no club at all.
    """
    pipeline = QualityPipeline(_NullTickets(), use_ai=False)  # type: ignore[arg-type]
    state = _RunState()
    state.normalized = [
        _envelope("stats", {"external_fixture_id": "fd-1",
                            "home": {"shots": 10}, "away": {"shots": 18}}),
        _envelope("odds_snapshot", {"external_fixture_id": "fd-1", "bookmaker": "bet365",
                                    "market": "1x2", "captured_at": "2023-08-12T00:00:00Z",
                                    "selections": [{"name": "home", "price": 2.1}]}),
        _envelope("fixture", {"home_team": {"name": "A", "club_id": "c1"},
                              "away_team": {"name": "B", "club_id": "c2"}}),
    ]
    # Before the fix this raised KeyError('home_team') on the first record.
    pipeline.resolve_entities({"state": state})


def test_fixture_without_resolved_clubs_still_flags_for_review():
    """The guard must skip records with NO clubs, not records with
    UNRESOLVED ones — those are exactly what entity resolution is for."""
    pipeline = QualityPipeline(_NullTickets(), use_ai=False)  # type: ignore[arg-type]
    state = _RunState()
    env = _envelope("fixture", {"home_team": {"name": "Burnley", "club_id": None},
                                "away_team": {"name": "Man City", "club_id": None}})
    state.normalized = [env]
    pipeline.resolve_entities({"state": state})
    assert env.get("_needs_entity_review") is True


# --- 2. quality scoring per entity type ------------------------------------

def test_odds_are_not_scored_against_fixture_fields():
    """Scored as a fixture, a complete odds snapshot lands near 0.1 — no
    clubs, no kick-off, no venue — and every bookmaker row for every match
    goes to human review."""
    odds = _envelope("odds_snapshot", {
        "external_fixture_id": "fd-1", "bookmaker": "bet365", "market": "1x2",
        "captured_at": "2023-08-12T00:00:00Z",
        "selections": [{"name": "home", "price": 2.1}, {"name": "away", "price": 3.6}],
    })
    value, _ = score(odds)
    assert value >= 0.9, f"a complete odds snapshot scored {value}"


def test_complete_stats_record_scores_high():
    stats = _envelope("stats", {
        "external_fixture_id": "fd-1",
        "home": {"shots": 10, "corners": 4},
        "away": {"shots": 18, "corners": 6},
    })
    value, _ = score(stats)
    assert value >= 0.9, f"a complete stats record scored {value}"


def test_empty_stats_record_scores_low():
    """`{}` for both sides is a record that says nothing, and must not pass
    for complete just because the keys exist."""
    stats = _envelope("stats", {"external_fixture_id": "fd-1", "home": {}, "away": {}})
    value, _ = score(stats)
    assert value < 0.7


def test_fixture_scoring_is_unchanged():
    """The fixture weights are the ones that were there. A regression here
    would silently re-grade every record already in the lake."""
    complete = _envelope("fixture", {
        "home_team": {"name": "A", "club_id": "c1", "short_name": "A"},
        "away_team": {"name": "B", "club_id": "c2", "short_name": "B"},
        "status": "finished", "score": {"home": 1, "away": 0},
        "venue": "Stadium", "scheduled_at": "2023-08-12T00:00:00Z",
        "status_detail": "FT",
    })
    value, _ = score(complete)
    assert value == pytest.approx(1.0, abs=0.001)


# --- 3. a dead worker must not report "running" ----------------------------

class _Store:
    """Execution store stub that records what the supervisor wrote."""

    def __init__(self, execution: Execution) -> None:
        self.execution = execution
        self.saves: list[str] = []

    def get(self, _id: str) -> Execution:
        return self.execution

    def save(self, execution: Execution) -> None:
        self.execution = execution
        self.saves.append(execution.state)


def test_a_crashing_worker_marks_the_execution_failed():
    """The eleven-hour bug. Without this, the row keeps whatever state was
    last written — "running" — and the console reports a job that no thread
    is executing."""
    from explorer.pipelines.engine import ExecutionRuntime, ExecutionSupervisor

    execution = Execution(pipeline_id="p1", state="running", jobs_total=5)
    store = _Store(execution)
    supervisor = ExecutionSupervisor(
        lake=None, pipeline_store=None, execution_store=store)  # type: ignore[arg-type]

    boom = KeyError("home_team")

    def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise boom

    supervisor._run_worker = explode  # type: ignore[method-assign]

    thread = threading.Thread(
        target=supervisor._run_bounded,
        args=("e1", None, ExecutionRuntime()),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=5)

    assert store.execution.state == "failed", (
        f"state = {store.execution.state!r} — a crashed execution that still "
        "reports 'running' is one nobody knows about"
    )
    # The reason has to reach the screen the operator is already looking at,
    # not only a stack trace among access logs.
    assert "KeyError" in store.execution.error
    assert "home_team" in store.execution.error


def test_the_semaphore_is_released_when_a_worker_crashes():
    """Otherwise the first two crashes exhaust max_concurrent and every later
    execution waits forever — which looks like 'queued', not 'broken'."""
    from explorer.pipelines.engine import ExecutionRuntime, ExecutionSupervisor

    store = _Store(Execution(pipeline_id="p1", state="running"))
    supervisor = ExecutionSupervisor(
        lake=None, pipeline_store=None, execution_store=store,  # type: ignore[arg-type]
        max_concurrent=1)

    def explode(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("boom")

    supervisor._run_worker = explode  # type: ignore[method-assign]

    for _ in range(3):
        t = threading.Thread(target=supervisor._run_bounded,
                             args=("e1", None, ExecutionRuntime()), daemon=True)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "worker did not finish — the semaphore was not released"
