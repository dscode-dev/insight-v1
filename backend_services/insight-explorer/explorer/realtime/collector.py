"""Real-time signal collector (ML-D Phase B, Decision B-1).

One background thread per active `Pipeline(type="realtime")` — directly
modeled on `explorer/scheduler.py`'s proven single-loop-thread shape. Inside
the loop, each of the pipeline's referenced, enabled `SignalSource`s is
polled in-thread once its own `poll_interval_s` has elapsed since it was
last polled; a broken source is caught, ticketed, and never kills the loop
(same isolation discipline as `JobRunner`). Capture is always persisted to
the `signals/` lake layer first; publishing (Decision B-2) is a separate,
best-effort step layered on top — see `explorer/realtime/publisher.py`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from explorer.collectors.http import PoliteFetcher
from explorer.datalake.lake import DataLake
from explorer.observability.logging import get_logger
from explorer.pipelines.store import PipelineNotFound, PipelineStore
from explorer.realtime.kinds import handler_for
from explorer.realtime.models import CapturedSignal, SignalSource
from explorer.realtime.store import SignalSourceNotFound, SignalSourceStore
from explorer.tickets.tickets import TicketStore

_log = get_logger("explorer.realtime.collector")
_TICK_S = 1.0  # how often the loop re-checks pending sources / stop


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class CollectorRuntime:
    stop: threading.Event = field(default_factory=threading.Event)
    started_at: str = ""
    signals_captured: int = 0
    errors: int = 0
    last_signal_at: str | None = None
    last_error_at: str | None = None
    last_error_message: str | None = None
    thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        total = self.signals_captured + self.errors
        return {
            "state": "running",
            "started_at": self.started_at,
            "signals_captured": self.signals_captured,
            "errors": self.errors,
            "error_rate": round(self.errors / total, 4) if total else 0.0,
            "last_signal_at": self.last_signal_at,
            "last_error_at": self.last_error_at,
            "last_error_message": self.last_error_message,
        }


class RealtimeNotRunning(RuntimeError):
    """No in-process runtime for this pipeline (never started, already
    stopped, or the process restarted since it was started)."""


class RealtimeCollector:
    def __init__(self, lake: DataLake, pipeline_store: PipelineStore,
                 source_store: SignalSourceStore, fetcher: PoliteFetcher | None = None,
                 publisher: Any = None) -> None:
        self.lake = lake
        self.pipeline_store = pipeline_store
        self.source_store = source_store
        self.fetcher = fetcher or PoliteFetcher()
        self.publisher = publisher  # optional SignalPublisher; None = lake-only
        self.tickets = TicketStore(lake.root)
        self._runtimes: dict[str, CollectorRuntime] = {}
        self._registry_lock = threading.Lock()

    # --- lifecycle -----------------------------------------------------

    def start(self, pipeline_id: str) -> dict[str, Any]:
        pipeline = self.pipeline_store.get(pipeline_id)
        if pipeline.type != "realtime":
            raise ValueError(
                f"pipeline {pipeline_id} is type={pipeline.type!r} — historical pipelines are "
                "executed via ExecutionSupervisor.start_execution, not start()")
        with self._registry_lock:
            existing = self._runtimes.get(pipeline_id)
            if existing and existing.thread and existing.thread.is_alive():
                return existing.status()
            runtime = CollectorRuntime()
            self._runtimes[pipeline_id] = runtime
        thread = threading.Thread(target=self._run, args=(pipeline_id, runtime),
                                  name=f"realtime-{pipeline_id[:8]}", daemon=True)
        runtime.thread = thread
        thread.start()
        return runtime.status()

    def stop(self, pipeline_id: str) -> None:
        runtime = self._require_runtime(pipeline_id)
        runtime.stop.set()

    def stop_all(self) -> None:
        """Best-effort graceful shutdown — signal every running loop to
        stop, without waiting (the process is exiting anyway)."""
        with self._registry_lock:
            runtimes = list(self._runtimes.values())
        for runtime in runtimes:
            runtime.stop.set()

    def restart(self, pipeline_id: str) -> dict[str, Any]:
        runtime = self._runtimes.get(pipeline_id)
        if runtime is not None:
            runtime.stop.set()
            if runtime.thread is not None:
                runtime.thread.join(timeout=_TICK_S * 3)
        return self.start(pipeline_id)

    def status(self, pipeline_id: str) -> dict[str, Any]:
        runtime = self._runtimes.get(pipeline_id)
        if runtime is None or not (runtime.thread and runtime.thread.is_alive()):
            return {"state": "stopped", "started_at": None, "signals_captured": 0, "errors": 0,
                    "error_rate": 0.0, "last_signal_at": None, "last_error_at": None,
                    "last_error_message": None}
        return runtime.status()

    def _require_runtime(self, pipeline_id: str) -> CollectorRuntime:
        runtime = self._runtimes.get(pipeline_id)
        if runtime is None:
            raise RealtimeNotRunning(pipeline_id)
        return runtime

    # --- loop ------------------------------------------------------------

    def _run(self, pipeline_id: str, runtime: CollectorRuntime) -> None:
        runtime.started_at = _now()
        _log.info("realtime_collector_start", pipeline_id=pipeline_id)
        last_polled: dict[str, float] = {}
        while not runtime.stop.is_set():
            try:
                pipeline = self.pipeline_store.get(pipeline_id)
            except PipelineNotFound:
                break
            if not pipeline.enabled or pipeline.type != "realtime":
                break
            now = time.monotonic()
            for source_id in pipeline.signal_source_ids:
                if runtime.stop.is_set():
                    break
                try:
                    source = self.source_store.get(source_id)
                except SignalSourceNotFound:
                    continue
                if not source.enabled:
                    continue
                if now - last_polled.get(source_id, 0.0) < max(1, source.poll_interval_s):
                    continue
                last_polled[source_id] = now
                self._poll_one(source, runtime)
            runtime.stop.wait(timeout=_TICK_S)
        _log.info("realtime_collector_stop", pipeline_id=pipeline_id,
                  signals_captured=runtime.signals_captured, errors=runtime.errors)

    def _poll_one(self, source: SignalSource, runtime: CollectorRuntime) -> None:
        handler = handler_for(source.kind)
        if handler is None:
            self._record_failure(source, runtime, f"no handler registered for kind={source.kind!r}")
            self.tickets.open(error_type="signal_source_unconfigured", source=source.name,
                              competition="", season="", entity_type="signal", severity="medium",
                              sample_payload={"source_id": source.source_id, "kind": source.kind})
            return
        t0 = time.monotonic()
        try:
            signals = handler.poll(source, self.fetcher)
        except Exception as exc:  # noqa: BLE001 - one broken source must never kill the loop
            self._record_failure(source, runtime, str(exc))
            self.tickets.open(error_type="signal_source_poll_failed", source=source.name,
                              competition="", season="", entity_type="signal", severity="medium",
                              sample_payload={"source_id": source.source_id, "error": str(exc)})
            return
        latency_ms = (time.monotonic() - t0) * 1000
        for signal in signals:
            signal.source_id = source.source_id
            signal.captured_at = signal.captured_at or _now()
            self._persist(signal, source)
            runtime.signals_captured += 1
            runtime.last_signal_at = _now()
        self._record_success(source, latency_ms, captured=len(signals))

    def _persist(self, signal: CapturedSignal, source: SignalSource) -> None:
        self.lake.append_signal(source.source_id, [signal.to_dict()])
        if self.publisher is not None:
            try:
                self.publisher.publish(signal)
            except Exception as exc:  # noqa: BLE001 - lake write already succeeded; publish is best-effort
                self.tickets.open(error_type="signal_publish_failed", source=source.name,
                                  competition="", season="", entity_type="signal", severity="low",
                                  sample_payload={"signal_id": signal.signal_id, "error": str(exc)})

    def _record_success(self, source: SignalSource, latency_ms: float, captured: int) -> None:
        metrics = dict(source.metrics)
        prior_polls = metrics.get("poll_successes", 0) + metrics.get("errors", 0)
        avg = metrics.get("avg_latency_ms") or 0.0
        metrics["avg_latency_ms"] = round(
            ((avg * prior_polls) + latency_ms) / (prior_polls + 1), 2) if prior_polls else round(latency_ms, 2)
        metrics["signals_captured"] = metrics.get("signals_captured", 0) + captured
        metrics["poll_successes"] = metrics.get("poll_successes", 0) + 1
        metrics["last_success_at"] = _now()
        total = metrics["poll_successes"] + metrics.get("errors", 0)
        metrics["success_rate"] = round(metrics["poll_successes"] / total, 4) if total else None
        self.source_store.update(source.source_id, status="healthy", metrics=metrics)

    def _record_failure(self, source: SignalSource, runtime: CollectorRuntime, message: str) -> None:
        runtime.errors += 1
        runtime.last_error_at = _now()
        runtime.last_error_message = message[:200]
        metrics = dict(source.metrics)
        metrics["errors"] = metrics.get("errors", 0) + 1
        metrics["last_error_at"] = _now()
        metrics["last_error_message"] = message[:200]
        total = metrics.get("poll_successes", 0) + metrics["errors"]
        metrics["success_rate"] = round(metrics.get("poll_successes", 0) / total, 4) if total else None
        self.source_store.update(source.source_id, status="degraded", metrics=metrics)
