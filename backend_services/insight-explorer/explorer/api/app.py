"""FastAPI app — Explorer Operations Center API (ML-B.6).

Read endpoints (all live, no cached/static JSON):
    GET /health  /explorer/health  /explorer/status  /explorer/runtime
    GET /explorer/jobs  /explorer/jobs/active  /explorer/jobs/history  /explorer/jobs/{id}
    GET /explorer/datasets  /explorer/datasets/{competition}
    GET /explorer/sources  /explorer/agents  /explorer/langgraph  /explorer/qwen
    GET /explorer/quality  /explorer/storage  /explorer/tickets  /explorer/scheduler
    GET /explorer/audit    /explorer/metrics

Control endpoints (audited):
    POST /explorer/jobs/start|pause|resume|restart|cancel
    POST /explorer/sources/enable|disable
    POST /explorer/runtime/reload
    POST /explorer/tickets/reprocess

When EXPLORER_RUN_SCHEDULER=1 the app starts the continuous scheduler in a
background thread and exposes it to the control endpoints.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from explorer.api.service import ExplorerReadService


def control_token_error(token: str | None) -> tuple[int, str] | None:
    expected = os.environ.get("EXPLORER_OPS_TOKEN", "")
    if not expected:
        return 503, "explorer_controls_disabled"
    if not token or not secrets.compare_digest(token, expected):
        return 401, "invalid_ops_token"
    return None


def create_app(service: ExplorerReadService | None = None, run_scheduler: bool | None = None) -> Any:
    try:
        from fastapi import Body, FastAPI, Header, HTTPException, Response
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fastapi not installed — run `poetry install --with api`") from exc

    svc = service or ExplorerReadService()
    if run_scheduler is None:
        run_scheduler = os.environ.get("EXPLORER_RUN_SCHEDULER", "0") == "1"
    app = FastAPI(title="Insight Explorer Operations", version="0.0.2")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )
    app.state.scheduler = None

    from explorer.ops.controls import ControlError, ExplorerControls
    from explorer.operations import explorer_operations, start_grpc_server

    app.state.operations_ready = False
    app.state.operations_grpc = None
    app.state.operations_service = explorer_operations(
        ready=lambda: bool(getattr(app.state, "operations_ready", False)),
        active_jobs=lambda: len(app.state.scheduler.state.completed) if getattr(app.state, "scheduler", None) else 0,
    )

    def controls() -> ExplorerControls:
        return ExplorerControls(scheduler=app.state.scheduler, root=svc.root)

    @app.on_event("startup")
    def _startup() -> None:  # pragma: no cover - exercised in the container
        if run_scheduler:
            from explorer.scheduler import Scheduler

            use_ai = os.environ.get("EXPLORER_USE_AI", "1") == "1"
            sched = Scheduler(use_ai=use_ai)
            sched.start_background()
            app.state.scheduler = sched
        app.state.operations_ready = True
        app.state.operations_grpc = start_grpc_server(
            app.state.operations_service,
            os.environ.get("OPERATIONS_GRPC_ADDR", "[::]:9082"),
        )

    @app.on_event("shutdown")
    def _operations_shutdown() -> None:
        app.state.operations_ready = False
        if app.state.operations_grpc is not None:
            app.state.operations_grpc.stop(grace=5)

    # --- health / status -------------------------------------------------

    @app.get("/health")
    @app.get("/explorer/health")
    def health() -> dict[str, Any]:
        sched = app.state.scheduler
        return {"status": "ok", "service": "insight-explorer", "version": "0.0.2",
                "scheduler": ({"status": sched.state.status, "current": sched.state.current,
                               "completed": len(sched.state.completed)} if sched else "disabled")}

    @app.get("/healthz")
    def operations_healthz() -> dict[str, object]:
        return app.state.operations_service.http_health()

    @app.get("/explorer/status")
    def status() -> dict[str, Any]:
        return svc.status()

    @app.get("/status")
    def operations_status() -> dict[str, object]:
        return app.state.operations_service.http_status()

    @app.get("/capabilities")
    def operations_capabilities() -> dict[str, object]:
        return app.state.operations_service.http_capabilities()

    @app.get("/metrics/summary")
    def operations_metrics() -> dict[str, object]:
        return app.state.operations_service.http_metrics()

    @app.get("/explorer/runtime")
    def runtime() -> dict[str, Any]:
        return svc.runtime()

    @app.get("/explorer/scheduler")
    def scheduler() -> dict[str, Any]:
        return svc.scheduler_state()

    # --- jobs ------------------------------------------------------------

    @app.get("/explorer/jobs")
    def list_jobs(status: str | None = None, competition: str | None = None,
                  season: str | None = None) -> list[dict[str, Any]]:
        return svc.jobs(status=status, competition=competition, season=season)

    @app.get("/explorer/jobs/active")
    def jobs_active() -> list[dict[str, Any]]:
        return svc.jobs_active()

    @app.get("/explorer/jobs/history")
    def jobs_history(limit: int = 100) -> list[dict[str, Any]]:
        return svc.jobs_history(limit=limit)

    @app.get("/explorer/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = svc.job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    # --- datasets / sources / AI / quality / storage ---------------------

    @app.get("/explorer/datasets")
    def datasets() -> list[dict[str, Any]]:
        return svc.datasets()

    @app.get("/explorer/datasets/{competition}")
    def dataset_detail(competition: str) -> dict[str, Any]:
        return svc.dataset_detail(competition)

    @app.get("/explorer/sources")
    def sources() -> list[dict[str, Any]]:
        return svc.sources()

    @app.get("/explorer/agents")
    def agents() -> dict[str, Any]:
        return svc.agents()

    @app.get("/explorer/langgraph")
    def langgraph() -> dict[str, Any]:
        return svc.langgraph()

    @app.get("/explorer/qwen")
    def qwen() -> dict[str, Any]:
        return svc.qwen()

    @app.get("/explorer/quality")
    def quality() -> dict[str, Any]:
        return svc.quality()

    @app.get("/explorer/storage")
    def storage() -> dict[str, Any]:
        return svc.storage()

    @app.get("/explorer/tickets")
    def list_tickets(status: str | None = "open") -> list[dict[str, Any]]:
        return svc.tickets(status=status)

    # --- ML-C quality endpoints -----------------------------------------

    @app.get("/explorer/entity-resolution")
    def entity_resolution() -> dict[str, Any]:
        return svc.entity_resolution()

    @app.get("/explorer/duplicates")
    def duplicates() -> dict[str, Any]:
        return svc.duplicates()

    @app.get("/explorer/quality/datasets")
    def quality_datasets() -> dict[str, Any]:
        return svc.quality_datasets()

    @app.get("/explorer/review")
    def review_queue(status: str = "pending", competition: str | None = None) -> dict[str, Any]:
        return svc.review_queue(status=status, competition=competition)

    @app.get("/explorer/analytics")
    def analytics() -> dict[str, Any]:
        return svc.analytics()

    @app.get("/explorer/audit")
    def audit(limit: int = 100) -> list[dict[str, Any]]:
        return svc.audit_log(limit=limit)

    @app.get("/explorer/metrics")
    def get_metrics() -> Any:
        return Response(content=svc.metrics_text(), media_type="text/plain; version=0.0.4")

    # --- controls (audited) ---------------------------------------------

    def _actor(x_operator: str | None) -> str:
        return x_operator or "console"

    def _authorize(x_ops_token: str | None) -> None:
        failure = control_token_error(x_ops_token)
        if failure:
            raise HTTPException(status_code=failure[0], detail=failure[1])

    def _run(fn) -> dict[str, Any]:
        try:
            return fn()
        except ControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/explorer/jobs/start")
    def jobs_start(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                   x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().start_job(body["competition"], body["season"], _actor(x_operator)))

    @app.post("/explorer/jobs/restart")
    def jobs_restart(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                     x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().restart_job(body["competition"], body["season"], _actor(x_operator)))

    @app.post("/explorer/jobs/pause")
    def jobs_pause(x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pause(_actor(x_operator)))

    @app.post("/explorer/jobs/resume")
    def jobs_resume(x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().resume(_actor(x_operator)))

    @app.post("/explorer/jobs/cancel")
    def jobs_cancel(x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().cancel(_actor(x_operator)))

    @app.post("/explorer/sources/enable")
    def sources_enable(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                       x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().enable_source(body["source"], _actor(x_operator)))

    @app.post("/explorer/sources/disable")
    def sources_disable(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                        x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().disable_source(body["source"], _actor(x_operator)))

    @app.post("/explorer/runtime/reload")
    def runtime_reload(x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().reload_runtime(_actor(x_operator)))

    @app.post("/explorer/tickets/reprocess")
    def tickets_reprocess(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                          x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().reprocess_ticket(body["ticket_id"], _actor(x_operator)))

    @app.post("/explorer/review/promote")
    def review_promote(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                       x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().review_promote(body["external_id"], _actor(x_operator)))

    @app.post("/explorer/review/reject")
    def review_reject(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                      x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().review_reject(body["external_id"], _actor(x_operator)))

    @app.post("/explorer/review/replay")
    def review_replay(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                      x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().review_replay(body["competition"], body["season"], _actor(x_operator)))

    return app
