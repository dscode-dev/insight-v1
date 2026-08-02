"""Consolidation Sprint 0 Task 0 — watcher thresholds promoted to
typed, validated configuration with metrics exposure.
"""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY
from pydantic import ValidationError

from atlas.config.settings import Settings
from atlas.watchers import WatcherRegistry, WatcherScheduler, export_watcher_config

BASE_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379/0",
    "INTERNAL_TOKEN": "test-token-1234567890",
    "ATLAS_ANVIL_API_BASE_URL": "https://gateway.test/v1",
    "ATLAS_ANVIL_API_KEY": "x" * 32,
}


def make_settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **BASE_ENV, **overrides)


def test_watcher_thresholds_have_sane_defaults() -> None:
    s = make_settings()
    assert s.market_drift_threshold == 0.03
    assert s.match_possession_growth_threshold == 10.0
    assert s.risk_accumulation_threshold == 4.0
    assert s.narrative_consensus_threshold == 0.2
    assert s.watcher_interval_seconds == 30
    assert s.watcher_jitter_seconds == 6.0


def test_watcher_thresholds_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_MARKET_DRIFT_THRESHOLD", "0.05")
    monkeypatch.setenv("ATLAS_MATCH_POSSESSION_GROWTH_THRESHOLD", "15")
    monkeypatch.setenv("ATLAS_RISK_ACCUMULATION_THRESHOLD", "6.5")
    monkeypatch.setenv("ATLAS_NARRATIVE_CONSENSUS_THRESHOLD", "0.35")
    monkeypatch.setenv("ATLAS_WATCHER_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("ATLAS_WATCHER_JITTER_SECONDS", "12")
    s = make_settings()
    assert s.market_drift_threshold == 0.05
    assert s.match_possession_growth_threshold == 15.0
    assert s.risk_accumulation_threshold == 6.5
    assert s.narrative_consensus_threshold == 0.35
    assert s.watcher_interval_seconds == 60
    assert s.watcher_jitter_seconds == 12.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ATLAS_MARKET_DRIFT_THRESHOLD", "0"),
        ("ATLAS_MARKET_DRIFT_THRESHOLD", "1.5"),
        ("ATLAS_MATCH_POSSESSION_GROWTH_THRESHOLD", "-3"),
        ("ATLAS_MATCH_POSSESSION_GROWTH_THRESHOLD", "150"),
        ("ATLAS_RISK_ACCUMULATION_THRESHOLD", "0"),
        ("ATLAS_NARRATIVE_CONSENSUS_THRESHOLD", "0"),
        ("ATLAS_NARRATIVE_CONSENSUS_THRESHOLD", "2"),
        ("ATLAS_WATCHER_INTERVAL_SECONDS", "0"),
    ],
)
def test_out_of_range_thresholds_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field, value)
    with pytest.raises(ValidationError):
        make_settings()


def test_jitter_must_fit_inside_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_WATCHER_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("ATLAS_WATCHER_JITTER_SECONDS", "30")
    with pytest.raises(ValidationError):
        make_settings()
    monkeypatch.setenv("ATLAS_WATCHER_JITTER_SECONDS", "-1")
    with pytest.raises(ValidationError):
        make_settings()


def test_scheduler_jitter_is_absolute_seconds() -> None:
    sched = WatcherScheduler(
        WatcherRegistry(), sink=None, interval_seconds=30.0, jitter_seconds=6.0
    )
    delays = [sched._next_delay() for _ in range(200)]
    assert all(24.0 <= d <= 36.0 for d in delays)
    # Zero jitter → exact interval.
    fixed = WatcherScheduler(
        WatcherRegistry(), sink=None, interval_seconds=30.0, jitter_seconds=0.0
    )
    assert fixed._next_delay() == 30.0
    # Oversized jitter is clamped so the delay can never go non-positive.
    clamped = WatcherScheduler(
        WatcherRegistry(), sink=None, interval_seconds=10.0, jitter_seconds=99.0
    )
    assert all(clamped._next_delay() > 0 for _ in range(200))


def test_config_exposed_as_metrics() -> None:
    export_watcher_config(
        market_drift_threshold=0.03,
        watcher_interval_seconds=30,
    )
    assert REGISTRY.get_sample_value(
        "atlas_watcher_config", {"parameter": "market_drift_threshold"}
    ) == 0.03
    assert REGISTRY.get_sample_value(
        "atlas_watcher_config", {"parameter": "watcher_interval_seconds"}
    ) == 30.0
