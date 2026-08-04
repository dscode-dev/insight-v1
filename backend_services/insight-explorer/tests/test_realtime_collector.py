import time

import pytest

from explorer.datalake.lake import DataLake
from explorer.pipelines.models import Pipeline
from explorer.pipelines.store import PipelineStore
from explorer.realtime.collector import RealtimeCollector, RealtimeNotRunning
from explorer.realtime.kinds import REGISTRY
from explorer.realtime.models import CapturedSignal, SignalSource
from explorer.realtime.store import SignalSourceStore


class _AlwaysOneSignalHandler:
    def poll(self, source, fetcher):
        return [CapturedSignal(signal_type="news", source_id=source.source_id, text="headline")]


class _AlwaysFailsHandler:
    def poll(self, source, fetcher):
        raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _register_test_handlers():
    REGISTRY["always-one"] = _AlwaysOneSignalHandler()
    REGISTRY["always-fails"] = _AlwaysFailsHandler()
    yield
    REGISTRY.pop("always-one", None)
    REGISTRY.pop("always-fails", None)


def _wait_for(predicate, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _setup(tmp_path):
    lake = DataLake(tmp_path)
    pipeline_store = PipelineStore(tmp_path)
    source_store = SignalSourceStore(tmp_path)
    collector = RealtimeCollector(lake, pipeline_store, source_store)
    return lake, pipeline_store, source_store, collector


def test_collector_captures_signals_and_persists_to_lake(tmp_path):
    lake, pipeline_store, source_store, collector = _setup(tmp_path)
    source = source_store.create(SignalSource(name="Test source", kind="always-one", poll_interval_s=1))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime", signal_source_ids=[source.source_id]))
    collector.start(pipeline.pipeline_id)
    assert _wait_for(lambda: collector.status(pipeline.pipeline_id)["signals_captured"] >= 1)
    collector.stop(pipeline.pipeline_id)

    files = list((tmp_path / "signals" / source.source_id).glob("*.jsonl"))
    assert files
    assert source_store.get(source.source_id).status == "healthy"


def test_collector_isolates_a_failing_source(tmp_path):
    lake, pipeline_store, source_store, collector = _setup(tmp_path)
    bad = source_store.create(SignalSource(name="Bad", kind="always-fails", poll_interval_s=1))
    good = source_store.create(SignalSource(name="Good", kind="always-one", poll_interval_s=1))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime",
                                              signal_source_ids=[bad.source_id, good.source_id]))
    collector.start(pipeline.pipeline_id)
    assert _wait_for(lambda: collector.status(pipeline.pipeline_id)["signals_captured"] >= 1
                     and collector.status(pipeline.pipeline_id)["errors"] >= 1)
    collector.stop(pipeline.pipeline_id)
    assert source_store.get(bad.source_id).status == "degraded"
    assert source_store.get(good.source_id).status == "healthy"


def test_disabled_source_is_never_polled(tmp_path):
    lake, pipeline_store, source_store, collector = _setup(tmp_path)
    source = source_store.create(SignalSource(name="x", kind="always-one", poll_interval_s=1, enabled=False))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime", signal_source_ids=[source.source_id]))
    collector.start(pipeline.pipeline_id)
    time.sleep(0.3)
    collector.stop(pipeline.pipeline_id)
    assert collector.status(pipeline.pipeline_id)["signals_captured"] == 0


def test_start_rejects_historical_pipeline(tmp_path):
    _, pipeline_store, _, collector = _setup(tmp_path)
    pipeline = pipeline_store.create(Pipeline(name="x", type="historical"))
    with pytest.raises(ValueError):
        collector.start(pipeline.pipeline_id)


def test_status_of_never_started_pipeline_is_stopped(tmp_path):
    _, _, _, collector = _setup(tmp_path)
    assert collector.status("unknown")["state"] == "stopped"


def test_stop_unknown_pipeline_raises(tmp_path):
    _, _, _, collector = _setup(tmp_path)
    with pytest.raises(RealtimeNotRunning):
        collector.stop("unknown")


def test_publish_failure_still_persists_to_lake_and_opens_ticket(tmp_path):
    """Decision B-2: lake write is authoritative, Redis publish is
    best-effort — a broken publisher must never lose a captured signal."""
    class _FailingPublisher:
        def publish(self, signal):
            raise RuntimeError("redis unreachable")

    lake, pipeline_store, source_store, _ = _setup(tmp_path)
    collector = RealtimeCollector(lake, pipeline_store, source_store, publisher=_FailingPublisher())
    source = source_store.create(SignalSource(name="x", kind="always-one", poll_interval_s=1))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime", signal_source_ids=[source.source_id]))

    collector.start(pipeline.pipeline_id)
    assert _wait_for(lambda: collector.status(pipeline.pipeline_id)["signals_captured"] >= 1)
    collector.stop(pipeline.pipeline_id)

    files = list((tmp_path / "signals" / source.source_id).glob("*.jsonl"))
    assert files, "signal must land in the lake even when publishing fails"
    assert any(t.error_type == "signal_publish_failed" for t in collector.tickets.all())
    # publish failure must not degrade the source itself — the poll succeeded
    assert source_store.get(source.source_id).status == "healthy"


def test_unconfigured_kind_opens_ticket_not_crash(tmp_path):
    lake, pipeline_store, source_store, collector = _setup(tmp_path)
    source = source_store.create(SignalSource(name="x", kind="no-such-kind", poll_interval_s=1))
    pipeline = pipeline_store.create(Pipeline(name="x", type="realtime", signal_source_ids=[source.source_id]))
    collector.start(pipeline.pipeline_id)
    assert _wait_for(lambda: collector.tickets.all())
    collector.stop(pipeline.pipeline_id)
    assert any(t.error_type == "signal_source_unconfigured" for t in collector.tickets.all())
