"""Continuous historical scheduler (ML-B.5 Steps: scheduler + resume).

Runs the fixed competition/season plan IN ORDER, persisting progress after
every task so a container restart RESUMES rather than restarting from zero.
State lives in the data lake (`reports/scheduler_state.json`) so it survives
container recreation as long as the data volume is mounted.

The scheduler runs each task through the multi-source job
(`explorer/jobs/multi.py`), which collects from every source that supports the
competition and records cross-source confidence.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from explorer.config import DATA_LAKE_ROOT
from explorer.datalake.lake import DataLake
from explorer.jobs.multi import run_multi_source
from explorer.jobs.runner import JobRunner
from explorer.observability.logging import get_logger
from explorer.sources import build_default_registry

# Fixed execution order (sprint spec).
PLAN: tuple[tuple[str, str], ...] = (
    ("brasileirao_serie_a", "2020"),
    ("brasileirao_serie_a", "2021"),
    ("brasileirao_serie_a", "2022"),
    ("brasileirao_serie_a", "2023"),
    ("brasileirao_serie_a", "2024"),
    ("libertadores", "2020"),
    ("libertadores", "2021"),
    ("libertadores", "2022"),
    ("libertadores", "2023"),
    ("libertadores", "2024"),
    ("world_cup", "2018"),
    ("world_cup", "2022"),
)


@dataclass
class SchedulerState:
    completed: list[list[str]] = field(default_factory=list)
    current: list[str] | None = None
    status: str = "idle"  # idle | running | completed
    started_at: str = ""
    updated_at: str = ""
    cycles: int = 0
    last_result: dict[str, Any] = field(default_factory=dict)

    def is_done(self, task: tuple[str, str]) -> bool:
        return list(task) in self.completed


class Scheduler:
    def __init__(self, lake: DataLake | None = None, use_ai: bool = True,
                 plan: tuple[tuple[str, str], ...] = PLAN, repeat: bool = False) -> None:
        self.lake = lake or DataLake(DATA_LAKE_ROOT)
        self.use_ai = use_ai
        self.plan = plan
        self.repeat = repeat
        self.log = get_logger("explorer.scheduler")
        # Built once and reused across every task for the scheduler's whole
        # lifetime: each adapter owns a PoliteFetcher/requests.Session, and
        # rebuilding the registry per task would tear down + recreate every
        # source's connection pool on each of the (potentially thousands of)
        # tasks a long-running scheduler executes.
        self.registry = build_default_registry()
        self._state_path = Path(self.lake.root) / "reports" / "scheduler_state.json"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._priority: list[tuple[str, str]] = []  # operator-enqueued tasks (run first)
        self._cancel_requested = False
        self.state = self._load()

    # --- operator controls (ML-B.6 Part 3) -------------------------------

    def _is_paused(self) -> bool:
        from explorer.ops import runtime_config

        return runtime_config.load(self.lake.root).scheduler_paused

    def pause(self) -> None:
        from explorer.ops import runtime_config

        cfg = runtime_config.load(self.lake.root)
        cfg.scheduler_paused = True
        runtime_config.save(cfg, self.lake.root)
        self.state.status = "paused"
        self._persist()

    def resume(self) -> None:
        from explorer.ops import runtime_config

        cfg = runtime_config.load(self.lake.root)
        cfg.scheduler_paused = False
        runtime_config.save(cfg, self.lake.root)
        self.state.status = "running"
        self._persist()

    def enqueue(self, competition: str, season: str) -> None:
        """Operator 'start job' — run this (competition, season) next."""
        self._priority.append((competition, season))

    def restart_task(self, competition: str, season: str) -> None:
        """Remove a completed task so it is collected again (resume-safe)."""
        self.state.completed = [c for c in self.state.completed
                                if c != [competition, season]]
        self.enqueue(competition, season)
        self._persist()

    def request_cancel(self) -> None:
        self._cancel_requested = True

    # --- persistence -----------------------------------------------------

    def _load(self) -> SchedulerState:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text("utf-8"))
                return SchedulerState(**data)
            except (json.JSONDecodeError, TypeError):
                pass
        return SchedulerState()

    def _persist(self) -> None:
        self.state.updated_at = _now()
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self.state), ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(self._state_path)  # atomic

    # --- lifecycle -------------------------------------------------------

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, name="explorer-scheduler",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        if not self.state.started_at:
            self.state.started_at = _now()
        self.log.info("scheduler_start", completed=len(self.state.completed),
                      plan=len(self.plan), repeat=self.repeat)
        while not self._stop.is_set():
            if self._is_paused():
                self.state.status = "paused"
                self._persist()
                self._stop.wait(timeout=10)
                continue
            ran_any = self.run_pending()
            if not ran_any:
                if self.repeat:
                    self.state.completed = []
                    self.state.cycles += 1
                    self._persist()
                    self.log.info("scheduler_cycle_restart", cycles=self.state.cycles)
                else:
                    self.state.status = "idle"
                    self._persist()
                    # stay alive; poll for operator-enqueued work + pause changes
                    self._stop.wait(timeout=15)
        self.log.info("scheduler_stopped")

    def _next_task(self) -> tuple[str, str] | None:
        if self._priority:
            return self._priority.pop(0)
        for task in self.plan:
            if not self.state.is_done(task):
                return task
        return None

    def run_pending(self) -> bool:
        """Run the next pending task (priority queue first, then plan).
        Returns False if nothing is pending."""
        task = self._next_task()
        if task is None:
            return False
        if self._stop.is_set():
            return True
        competition, season = task
        runner = JobRunner(lake=self.lake, use_ai=self.use_ai)
        self.state.current = list(task)
        self.state.status = "running"
        self._cancel_requested = False
        self._persist()
        self.log.info("task_start", competition=competition, season=season)
        try:
            result = run_multi_source(competition, season, runner=runner, registry=self.registry)
            self.state.last_result = result
        except Exception as exc:  # noqa: BLE001 - never let one task kill the loop
            self.log.error("task_error", competition=competition, season=season, error=str(exc))
            self.state.last_result = {"error": str(exc)}
        if list(task) not in self.state.completed:
            self.state.completed.append(list(task))
        self.state.current = None
        self._persist()
        self.log.info("task_done", competition=competition, season=season)
        return True


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
