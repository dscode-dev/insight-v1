"""Historical execution engine (ML-D Mission Center).

`decompose()` turns a `Pipeline`'s declared scope into a task list, reusing
`run_multi_source`/`JobRunner` for the actual collection — no new collection
logic. `ExecutionSupervisor` gives every `Execution` its own worker thread
and its own `{pause, stop}` events, so pausing one execution never touches
another's — the concrete fix for the legacy `Scheduler`'s single global
`scheduler_paused` flag.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from explorer.datalake.lake import DataLake
from explorer.jobs.multi import run_multi_source
from explorer.jobs.runner import JobRunner
from explorer.observability.logging import get_logger
from explorer.pipelines.catalog import COLLECTIBLE_THEMES
from explorer.pipelines.executions.models import Execution
from explorer.pipelines.executions.store import ExecutionStore
from explorer.pipelines.models import Pipeline
from explorer.pipelines.seasons import resolve_seasons
from explorer.pipelines.store import PipelineStore

_log = get_logger("explorer.pipelines.engine")


def decompose(pipeline: Pipeline) -> list[dict[str, Any]]:
    """A pipeline with no collectible theme decomposes to zero tasks — its
    execution completes immediately rather than looping forever over work
    that no adapter can actually perform (see catalog.COLLECTIBLE_THEMES)."""
    if not set(pipeline.themes) & COLLECTIBLE_THEMES:
        return []
    tasks: list[dict[str, Any]] = []
    for competition in pipeline.competitions:
        for season in resolve_seasons(competition, pipeline.duration):
            tasks.append({"competition": competition, "season": season, "status": "pending"})
    return tasks


@dataclass
class ExecutionRuntime:
    """In-process only — pause/resume/stop control lives here, not on disk.
    Same single-container assumption as the legacy Scheduler: control only
    works while the owning process is alive."""

    pause: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)


class ExecutionNotRunning(RuntimeError):
    """No in-process runtime for this execution (already finished, or the
    process restarted since it was started)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ExecutionSupervisor:
    def __init__(self, lake: DataLake, pipeline_store: PipelineStore, execution_store: ExecutionStore,
                 use_ai: bool = False, max_concurrent: int = 2, registry: list[Any] | None = None) -> None:
        self.lake = lake
        self.pipeline_store = pipeline_store
        self.execution_store = execution_store
        self.use_ai = use_ai
        self.registry = registry  # None = each run_multi_source call uses the real default registry
        self._semaphore = threading.Semaphore(max_concurrent)
        self._runtimes: dict[str, ExecutionRuntime] = {}
        self._registry_lock = threading.Lock()

    # --- lifecycle ---------------------------------------------------------

    def start_execution(self, pipeline_id: str) -> Execution:
        pipeline = self.pipeline_store.get(pipeline_id)
        if pipeline.type != "historical":
            raise ValueError(
                f"pipeline {pipeline_id} is type={pipeline.type!r} — realtime pipelines are "
                "started/stopped via RealtimeCollector.start/stop, not execute()")
        tasks = decompose(pipeline)
        execution = Execution(
            pipeline_id=pipeline_id, pipeline_name=pipeline.name,
            jobs_total=len(tasks), jobs_remaining=len(tasks),
            source_count=len([s for s in pipeline.sources if s.enabled]),
            tasks=tasks,
        )
        execution = self.execution_store.create(execution)
        runtime = ExecutionRuntime()
        with self._registry_lock:
            self._runtimes[execution.execution_id] = runtime
        thread = threading.Thread(
            target=self._run_bounded, args=(execution.execution_id, pipeline, runtime),
            name=f"execution-{execution.execution_id[:8]}", daemon=True)
        thread.start()
        return execution

    def pause(self, execution_id: str) -> None:
        """Only flips the event — the worker thread is the sole writer of
        `execution.state` (see `_run_worker`). Writing `state` here too would
        race the worker's own next save and get silently clobbered."""
        self._require_runtime(execution_id).pause.set()

    def resume(self, execution_id: str) -> None:
        self._require_runtime(execution_id).pause.clear()

    def stop(self, execution_id: str) -> None:
        runtime = self._require_runtime(execution_id)
        runtime.stop.set()
        runtime.pause.clear()  # unblock a paused worker so it can observe stop and exit

    def _require_runtime(self, execution_id: str) -> ExecutionRuntime:
        with self._registry_lock:
            runtime = self._runtimes.get(execution_id)
        if runtime is None:
            raise ExecutionNotRunning(execution_id)
        return runtime

    # --- worker --------------------------------------------------------

    def _run_bounded(self, execution_id: str, pipeline: Pipeline, runtime: ExecutionRuntime) -> None:
        self._semaphore.acquire()
        try:
            self._run_worker(execution_id, pipeline, runtime)
        finally:
            self._semaphore.release()
            with self._registry_lock:
                self._runtimes.pop(execution_id, None)

    def _run_worker(self, execution_id: str, pipeline: Pipeline, runtime: ExecutionRuntime) -> None:
        execution = self.execution_store.get(execution_id)
        runner = JobRunner(lake=self.lake, use_ai=self.use_ai)
        allowed = {s.name for s in pipeline.sources if s.enabled}
        execution.state = "running"
        execution.started_at = _now()
        self.execution_store.save(execution)
        t0 = time.monotonic()
        _log.info("execution_start", execution_id=execution_id, pipeline_id=pipeline.pipeline_id,
                  jobs_total=execution.jobs_total)

        stopped = False
        for task in execution.tasks:
            if runtime.stop.is_set():
                stopped = True
                break
            if runtime.pause.is_set():
                execution.state = "paused"
                self.execution_store.save(execution)
                while runtime.pause.is_set() and not runtime.stop.is_set():
                    runtime.stop.wait(timeout=0.2)
                if runtime.stop.is_set():
                    stopped = True
                    break
                execution.state = "running"
                self.execution_store.save(execution)

            result = run_multi_source(task["competition"], task["season"], runner=runner,
                                      allowed_sources=allowed, registry=self.registry,
                                      execution_id=execution_id)
            validated = sum(s["validated"] for s in result["per_source"])
            task["status"] = "done"
            task["validated"] = validated
            execution.jobs_completed += 1
            execution.jobs_remaining = execution.jobs_total - execution.jobs_completed
            execution.records += validated
            for s in result["per_source"]:
                execution.source_contribution[s["source"]] = (
                    execution.source_contribution.get(s["source"], 0) + s["validated"])
                if s["status"] not in ("completed", "skipped"):
                    execution.failed_source_jobs += 1
            execution.duration_seconds = round(time.monotonic() - t0, 3)
            execution.progress = (
                execution.jobs_completed / execution.jobs_total if execution.jobs_total else 1.0)
            execution.throughput_records_per_second = round(
                execution.records / execution.duration_seconds, 3) if execution.duration_seconds else 0.0
            remaining = execution.jobs_total - execution.jobs_completed
            avg_per_job = execution.duration_seconds / execution.jobs_completed
            execution.eta_seconds = round(avg_per_job * remaining, 1) if remaining else 0.0
            self.execution_store.save(execution)

        execution.state = "stopped" if stopped else "completed"
        execution.ended_at = _now()
        if not stopped:
            execution.progress = 1.0
            execution.eta_seconds = 0.0
        self.execution_store.save(execution)
        _log.info("execution_done", execution_id=execution_id, state=execution.state,
                  jobs_completed=execution.jobs_completed, records=execution.records)


class RecurringDispatcher:
    """Background loop: for every enabled `duration.mode == "recurring"`
    pipeline with no execution currently pending/running, starts a new one.
    This is what makes "recurring" mean something beyond a label — the
    functional replacement for the legacy Scheduler's infinite `run_forever`."""

    def __init__(self, supervisor: ExecutionSupervisor, poll_interval_s: float = 60.0) -> None:
        self.supervisor = supervisor
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="recurring-pipeline-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - one bad pipeline must never kill the dispatcher
                _log.error("recurring_dispatch_error")
            self._stop.wait(timeout=self.poll_interval_s)

    def _tick(self) -> None:
        for pipeline in self.supervisor.pipeline_store.list():
            if not pipeline.enabled or pipeline.type != "historical":
                continue
            if (pipeline.duration or {}).get("mode") != "recurring":
                continue
            store = self.supervisor.execution_store
            in_flight = store.list(pipeline_id=pipeline.pipeline_id, state="running")
            pending = store.list(pipeline_id=pipeline.pipeline_id, state="pending")
            if in_flight or pending:
                continue
            self.supervisor.start_execution(pipeline.pipeline_id)
