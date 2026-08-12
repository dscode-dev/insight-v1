"""ATLAS-BACKTEST-A2 — Explorer adapter + operational service (no infra)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas.backtest import (
    ExplorerDatasetAdapter,
    ReplayService,
    scenario_from_dataset,
    scenario_from_match,
    scenario_from_season,
)
from atlas.intelligence.historical import HistoricalDataset, HistoricalRecord, stable_id


def _record(uid: str, *, season: str = "2024", month: int = 5) -> HistoricalRecord:
    return HistoricalRecord(
        uid=uid,
        competition="brasileirao",
        season=season,
        kickoff_at=datetime(2024, month, 1, tzinfo=timezone.utc),
        home="Flamengo",
        away="Palmeiras",
        home_score=1,
        away_score=1,
        label="draw",
        sources=("espn",),
        features={"sentiment_delta": 0.2, "momentum_score": 0.5},
    )


def _dataset() -> HistoricalDataset:
    return HistoricalDataset([_record("m1", month=5), _record("m2", month=6)])


def test_adapter_reconstructs_deterministic_inputs_from_real_features() -> None:
    adapter = ExplorerDatasetAdapter()
    inputs = adapter.record_to_inputs(_record("m1"))
    # Deterministic id (uuid5) + REAL feature vector, nothing fabricated.
    assert inputs.canonical_match_id == stable_id("replay-match", "m1")
    assert inputs.features == {"sentiment_delta": 0.2, "momentum_score": 0.5}
    assert inputs.minute is None  # not fabricated for a completed match


def test_scenario_builders_converge_and_order_deterministically() -> None:
    dataset = _dataset()
    match = scenario_from_match(dataset, "m1")
    season = scenario_from_season(dataset, "brasileirao", "2024")
    full = scenario_from_dataset(dataset)
    assert [s.label for s in match.steps] == ["m1"]
    assert [s.label for s in season.steps] == ["m1", "m2"]  # kickoff order
    assert full.source == "dataset" and len(full.steps) == 2


class _FakeEmitter:
    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(self, event_type: str, **kwargs) -> None:
        self.events.append(event_type)


@pytest.mark.asyncio
async def test_service_lifecycle_artifacts_and_ioc_events() -> None:
    emitter = _FakeEmitter()
    service = ReplayService(events=emitter)
    execution = await service.run_now(
        scenario_from_dataset(_dataset()), dataset_id="ds1", requester="tester"
    )
    # Lifecycle + persisted fields.
    assert execution.status == "completed"
    assert execution.started_at and execution.finished_at and execution.duration_ms is not None
    assert execution.replay_hash and execution.requester == "tester"
    assert "report" in execution.artifact_keys
    # Artifacts reproducible.
    artifacts = service.artifacts(execution.execution_id)
    assert artifacts.replay_hash == execution.replay_hash
    assert service.report(execution.execution_id) is not None
    # IOC events reuse the canonical bus, in deterministic order (incl. the
    # ATLAS-BACKTEST-B quality-gate events).
    assert emitter.events == [
        "replay_submitted", "replay_started", "dataset_loaded",
        "trend_generation_started", "trend_generation_finished", "report_generated",
        "replay_quality_started", "detector_evaluated", "quality_metrics_generated",
        "promotion_report_generated", "replay_quality_completed", "replay_completed",
    ]


@pytest.mark.asyncio
async def test_repeated_execution_is_reproducible() -> None:
    service = ReplayService()
    a = await service.run_now(scenario_from_dataset(_dataset()))
    b = await service.run_now(scenario_from_dataset(_dataset()))
    assert a.replay_hash == b.replay_hash


def test_cancel_guards() -> None:
    service = ReplayService()
    assert service.cancel("nope") is None
