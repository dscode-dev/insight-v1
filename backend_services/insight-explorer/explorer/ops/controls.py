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
    def __init__(self, scheduler: Any = None, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.scheduler = scheduler
        self.root = Path(root)
        self.telemetry = Telemetry(self.root)

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
