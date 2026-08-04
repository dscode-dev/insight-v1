"""Operator controls (ML-B.6 Part 3). Every action is audited to
reports/telemetry/audit.jsonl. Controls act on the live in-process Scheduler
(single-container design) and the persisted runtime config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from explorer.config import DATA_LAKE_ROOT
from explorer.observability.telemetry import Telemetry
from explorer.ops import runtime_config


class ControlError(RuntimeError):
    pass


class ExplorerControls:
    def __init__(self, scheduler: Any = None, root: Path | str = DATA_LAKE_ROOT,
                 supervisor: Any = None, collector: Any = None) -> None:
        self.scheduler = scheduler
        self.root = Path(root)
        self.telemetry = Telemetry(self.root)
        self.supervisor = supervisor
        self.collector = collector

    def _require_supervisor(self) -> Any:
        if self.supervisor is None:
            raise ControlError("pipeline execution engine not running in this process")
        return self.supervisor

    def _require_collector(self) -> Any:
        if self.collector is None:
            raise ControlError("realtime signal collector not running in this process")
        return self.collector

    def _audit(self, actor: str, action: str, params: dict[str, Any], result: str) -> dict[str, Any]:
        self.telemetry.audit(actor=actor or "unknown", action=action, params=params, result=result)
        return {"action": action, "params": params, "result": result, "actor": actor or "unknown"}

    def _require_scheduler(self) -> Any:
        if self.scheduler is None:
            raise ControlError("scheduler not running in this process")
        return self.scheduler

    # --- jobs -----------------------------------------------------------

    def start_job(self, competition: str, season: str, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().enqueue(competition, season)
        return self._audit(actor, "jobs.start", {"competition": competition, "season": season},
                           "enqueued")

    def restart_job(self, competition: str, season: str, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().restart_task(competition, season)
        return self._audit(actor, "jobs.restart", {"competition": competition, "season": season},
                           "re-enqueued")

    def pause(self, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().pause()
        return self._audit(actor, "jobs.pause", {}, "paused")

    def resume(self, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().resume()
        return self._audit(actor, "jobs.resume", {}, "resumed")

    def cancel(self, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().request_cancel()
        return self._audit(actor, "jobs.cancel", {}, "cancel_requested")

    # --- sources --------------------------------------------------------

    def enable_source(self, name: str, actor: str = "") -> dict[str, Any]:
        cfg = runtime_config.load(self.root)
        cfg.disabled_sources = [s for s in cfg.disabled_sources if s != name]
        runtime_config.save(cfg, self.root)
        return self._audit(actor, "sources.enable", {"source": name}, "enabled")

    def disable_source(self, name: str, actor: str = "") -> dict[str, Any]:
        cfg = runtime_config.load(self.root)
        if name not in cfg.disabled_sources:
            cfg.disabled_sources.append(name)
        runtime_config.save(cfg, self.root)
        return self._audit(actor, "sources.disable", {"source": name}, "disabled")

    # --- runtime + tickets ----------------------------------------------

    def reload_runtime(self, actor: str = "") -> dict[str, Any]:
        cfg = runtime_config.load(self.root)
        return self._audit(actor, "runtime.reload",
                           {"disabled_sources": cfg.disabled_sources,
                            "scheduler_paused": cfg.scheduler_paused}, "reloaded")

    # --- review backlog (ML-C Part 5) -----------------------------------

    def review_promote(self, external_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.ops.review import ReviewStore

        try:
            res = ReviewStore(self.root).promote(external_id)
        except KeyError as exc:
            raise ControlError(str(exc)) from exc
        return self._audit(actor, "review.promote", {"external_id": external_id}, str(res))

    def review_reject(self, external_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.ops.review import ReviewStore

        try:
            res = ReviewStore(self.root).reject(external_id)
        except KeyError as exc:
            raise ControlError(str(exc)) from exc
        return self._audit(actor, "review.reject", {"external_id": external_id}, str(res))

    def review_replay(self, competition: str, season: str, actor: str = "") -> dict[str, Any]:
        self._require_scheduler().restart_task(competition, season)
        return self._audit(actor, "review.replay", {"competition": competition, "season": season},
                           "re-collection enqueued")

    def reprocess_ticket(self, ticket_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.api.service import ExplorerReadService

        svc = ExplorerReadService(self.root)
        ticket = next((t for t in svc.tickets(status=None) if t.get("ticket_id") == ticket_id), None)
        if ticket is None:
            raise ControlError(f"ticket {ticket_id} not found")
        comp, season = ticket.get("competition"), ticket.get("season")
        if self.scheduler is not None and comp and season:
            self.scheduler.restart_task(comp, season)
            result = "re-collection enqueued"
        else:
            result = "acknowledged (no scheduler / no competition)"
        return self._audit(actor, "tickets.reprocess",
                           {"ticket_id": ticket_id, "competition": comp, "season": season}, result)

    # --- pipelines / executions (ML-D Mission Center) --------------------

    def pipeline_create(self, draft: dict[str, Any], actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.models import Pipeline
        from explorer.pipelines.store import PipelineStore

        pipeline = PipelineStore(self.root).create(Pipeline.from_dict(draft))
        result = self._audit(actor, "pipelines.create", {"name": pipeline.name}, "created")
        result["pipeline_id"] = pipeline.pipeline_id
        return result

    def pipeline_update(self, pipeline_id: str, changes: dict[str, Any], actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound, PipelineStore

        try:
            updated = PipelineStore(self.root).update(pipeline_id, **changes)
        except PipelineNotFound as exc:
            raise ControlError(str(exc)) from exc
        result = self._audit(actor, "pipelines.update", {"pipeline_id": pipeline_id}, "updated")
        result["version"] = updated.version
        return result

    def pipeline_execute(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound

        try:
            execution = self._require_supervisor().start_execution(pipeline_id)
        except (PipelineNotFound, ValueError) as exc:
            raise ControlError(str(exc)) from exc
        result = self._audit(actor, "pipelines.execute", {"pipeline_id": pipeline_id},
                             f"execution {execution.execution_id} started")
        result["execution_id"] = execution.execution_id
        return result

    def pipeline_duplicate(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound, PipelineStore

        try:
            clone = PipelineStore(self.root).duplicate(pipeline_id)
        except PipelineNotFound as exc:
            raise ControlError(str(exc)) from exc
        result = self._audit(actor, "pipelines.duplicate", {"pipeline_id": pipeline_id},
                             f"cloned as {clone.pipeline_id}")
        result["pipeline_id"] = clone.pipeline_id
        return result

    def pipeline_delete(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound, PipelineStore

        try:
            PipelineStore(self.root).delete(pipeline_id)
        except PipelineNotFound as exc:
            raise ControlError(str(exc)) from exc
        return self._audit(actor, "pipelines.delete", {"pipeline_id": pipeline_id}, "deleted")

    def execution_pause(self, execution_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.engine import ExecutionNotRunning

        try:
            self._require_supervisor().pause(execution_id)
        except ExecutionNotRunning as exc:
            raise ControlError(f"execution {exc} is not currently running in this process") from exc
        return self._audit(actor, "executions.pause", {"execution_id": execution_id}, "paused")

    def execution_resume(self, execution_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.engine import ExecutionNotRunning

        try:
            self._require_supervisor().resume(execution_id)
        except ExecutionNotRunning as exc:
            raise ControlError(f"execution {exc} is not currently running in this process") from exc
        return self._audit(actor, "executions.resume", {"execution_id": execution_id}, "resumed")

    def execution_stop(self, execution_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.engine import ExecutionNotRunning

        try:
            self._require_supervisor().stop(execution_id)
        except ExecutionNotRunning as exc:
            raise ControlError(f"execution {exc} is not currently running in this process") from exc
        return self._audit(actor, "executions.stop", {"execution_id": execution_id}, "stopped")

    # --- realtime signal sources / pipelines (ML-D Phase B) ---------------

    def signal_source_create(self, draft: dict[str, Any], actor: str = "") -> dict[str, Any]:
        from explorer.realtime.models import SignalSource
        from explorer.realtime.store import SignalSourceStore

        source = SignalSourceStore(self.root).create(SignalSource.from_dict(draft))
        result = self._audit(actor, "realtime.sources.create", {"name": source.name}, "created")
        result["source_id"] = source.source_id
        return result

    def signal_source_update(self, source_id: str, changes: dict[str, Any], actor: str = "") -> dict[str, Any]:
        from explorer.realtime.store import SignalSourceNotFound, SignalSourceStore

        try:
            SignalSourceStore(self.root).update(source_id, **changes)
        except SignalSourceNotFound as exc:
            raise ControlError(str(exc)) from exc
        return self._audit(actor, "realtime.sources.update", {"source_id": source_id}, "updated")

    def signal_source_delete(self, source_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.realtime.store import SignalSourceNotFound, SignalSourceStore

        try:
            SignalSourceStore(self.root).delete(source_id)
        except SignalSourceNotFound as exc:
            raise ControlError(str(exc)) from exc
        return self._audit(actor, "realtime.sources.delete", {"source_id": source_id}, "deleted")

    def pipeline_start(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound

        try:
            status = self._require_collector().start(pipeline_id)
        except (PipelineNotFound, ValueError) as exc:
            raise ControlError(str(exc)) from exc
        result = self._audit(actor, "realtime.pipelines.start", {"pipeline_id": pipeline_id}, "started")
        result["status"] = status
        return result

    def pipeline_stop(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.realtime.collector import RealtimeNotRunning

        try:
            self._require_collector().stop(pipeline_id)
        except RealtimeNotRunning as exc:
            raise ControlError(f"realtime pipeline {exc} is not currently running in this process") from exc
        return self._audit(actor, "realtime.pipelines.stop", {"pipeline_id": pipeline_id}, "stopped")

    def pipeline_restart(self, pipeline_id: str, actor: str = "") -> dict[str, Any]:
        from explorer.pipelines.store import PipelineNotFound

        try:
            status = self._require_collector().restart(pipeline_id)
        except (PipelineNotFound, ValueError) as exc:
            raise ControlError(str(exc)) from exc
        result = self._audit(actor, "realtime.pipelines.restart", {"pipeline_id": pipeline_id}, "restarted")
        result["status"] = status
        return result
