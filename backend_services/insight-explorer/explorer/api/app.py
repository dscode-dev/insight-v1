"""FastAPI app — Explorer Operations Center API (ML-B.6).

Read endpoints (all live, no cached/static JSON; require X-Ops-Token like the
control endpoints — this surface exposes full audit/job/ticket telemetry):
    GET /explorer/status  /explorer/runtime
    GET /explorer/jobs  /explorer/jobs/active  /explorer/jobs/history  /explorer/jobs/{id}
    GET /explorer/datasets  /explorer/datasets/{competition}
    GET /explorer/sources  /explorer/agents  /explorer/langgraph  /explorer/qwen
    GET /explorer/quality  /explorer/storage  /explorer/tickets  /explorer/scheduler
    GET /explorer/audit    /explorer/metrics
    GET /explorer/pipelines  /explorer/pipelines/catalog  /explorer/pipelines/{id}
    GET /explorer/executions  /explorer/executions/{id}(/jobs|/dataset)
    GET /explorer/pipelines/{id}/status  (realtime collector heartbeat)
    GET /explorer/realtime/sources  /explorer/realtime/sources/{id}  (api_key masked)

Unauthenticated (liveness/readiness probes only, no data):
    GET /health  /explorer/health  /healthz  /status  /capabilities  /metrics/summary

Control endpoints (audited):
    POST /explorer/jobs/start|pause|resume|restart|cancel
    POST /explorer/sources/enable|disable
    POST /explorer/runtime/reload
    POST /explorer/tickets/reprocess
    POST /explorer/pipelines  (create)      PUT/DELETE /explorer/pipelines/{id}
    POST /explorer/pipelines/{id}/duplicate|execute   (type=historical)
    POST /explorer/pipelines/{id}/start|stop|restart  (type=realtime)
    POST /explorer/pipelines/estimate       (pure, unaudited)
    POST /explorer/executions/{id}/pause|resume|stop
    POST /explorer/realtime/sources  (create)   PUT/DELETE /explorer/realtime/sources/{id}

When EXPLORER_RUN_SCHEDULER=1 the app seeds the legacy PLAN as a default
Mission Center pipeline (if not already migrated) and starts the
RecurringDispatcher, which replaces the old fixed Scheduler loop (Decision
A-2, ML-D). The pipeline execution engine (ExecutionSupervisor) itself is
always constructed at startup regardless of that flag, so `execute`/
`pause`/`resume`/`stop` work even when the always-on dispatcher is off.
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
        from fastapi import Body, Depends, FastAPI, Header, HTTPException, Response
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
    app.state.scheduler = None  # legacy fallback; not started by default post-migration (Decision A-2)
    app.state.supervisor = None
    app.state.dispatcher = None
    app.state.collector = None  # RealtimeCollector (ML-D Phase B)

    from explorer.operations import explorer_operations, start_grpc_server
    from explorer.ops.controls import ControlError, ExplorerControls

    app.state.operations_ready = False
    app.state.operations_grpc = None
    app.state.operations_service = explorer_operations(
        ready=lambda: bool(getattr(app.state, "operations_ready", False)),
        active_jobs=lambda: len(svc.executions(state="running")),
    )

    def controls() -> ExplorerControls:
        return ExplorerControls(scheduler=app.state.scheduler, root=svc.root,
                                supervisor=app.state.supervisor, collector=app.state.collector)

    def _authorize(x_ops_token: str | None) -> None:
        failure = control_token_error(x_ops_token)
        if failure:
            raise HTTPException(status_code=failure[0], detail=failure[1])

    def _require_ops_token(x_ops_token: str | None = Header(None)) -> None:
        """Dependency for every read endpoint that exposes job/audit/ticket
        data — this surface is only network-isolated, not auth-isolated, so
        it must not be readable without the same token the control endpoints
        already require."""
        _authorize(x_ops_token)

    _auth = [Depends(_require_ops_token)]

    @app.on_event("startup")
    def _startup() -> None:  # pragma: no cover - exercised in the container
        from explorer.datalake.lake import DataLake
        from explorer.pipelines.engine import ExecutionSupervisor, RecurringDispatcher
        from explorer.pipelines.executions.store import ExecutionStore
        from explorer.pipelines.migration import seed_default_pipeline
        from explorer.pipelines.store import PipelineStore
        from explorer.realtime.collector import RealtimeCollector
        from explorer.realtime.store import SignalSourceStore

        use_ai = os.environ.get("EXPLORER_USE_AI", "1") == "1"
        lake = DataLake(svc.root)
        pipeline_store = PipelineStore(svc.root)
        execution_store = ExecutionStore(svc.root)
        seed_default_pipeline(lake, pipeline_store, execution_store)
        max_concurrent = int(os.environ.get("EXPLORER_MAX_CONCURRENT_EXECUTIONS", "2"))
        supervisor = ExecutionSupervisor(lake, pipeline_store, execution_store, use_ai=use_ai,
                                         max_concurrent=max_concurrent)
        app.state.supervisor = supervisor

        publisher = None
        if os.environ.get("EXPLORER_REDIS_URL"):
            from explorer.realtime.publisher import SignalPublisher

            publisher = SignalPublisher()
        app.state.collector = RealtimeCollector(
            lake, pipeline_store, SignalSourceStore(svc.root), publisher=publisher)

        if run_scheduler:
            # Mission Center's ExecutionSupervisor + RecurringDispatcher replace the
            # legacy fixed Scheduler/PLAN loop (Decision A-2) — the migrated default
            # pipeline above is what the dispatcher keeps re-running.
            dispatcher = RecurringDispatcher(supervisor)
            dispatcher.start()
            app.state.dispatcher = dispatcher
        app.state.operations_ready = True
        app.state.operations_grpc = start_grpc_server(
            app.state.operations_service,
            os.environ.get("OPERATIONS_GRPC_ADDR", "[::]:9082"),
        )

    @app.on_event("shutdown")
    def _operations_shutdown() -> None:
        app.state.operations_ready = False
        if app.state.dispatcher is not None:
            app.state.dispatcher.stop()
        if app.state.collector is not None:
            app.state.collector.stop_all()
        if app.state.operations_grpc is not None:
            app.state.operations_grpc.stop(grace=5)

    # --- health / status -------------------------------------------------

    @app.get("/health")
    @app.get("/explorer/health")
    def health() -> dict[str, Any]:
        dispatcher = app.state.dispatcher
        return {"status": "ok", "service": "insight-explorer", "version": "0.0.2",
                "pipeline_engine": "running" if app.state.supervisor else "disabled",
                "recurring_dispatcher": "running" if dispatcher and dispatcher.is_running else "disabled"}

    @app.get("/healthz")
    def operations_healthz() -> dict[str, object]:
        return app.state.operations_service.http_health()

    @app.get("/explorer/status", dependencies=_auth)
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

    @app.get("/explorer/runtime", dependencies=_auth)
    def runtime() -> dict[str, Any]:
        return svc.runtime()

    @app.get("/explorer/scheduler", dependencies=_auth)
    def scheduler() -> dict[str, Any]:
        return svc.scheduler_state()

    # --- jobs ------------------------------------------------------------

    @app.get("/explorer/jobs", dependencies=_auth)
    def list_jobs(status: str | None = None, competition: str | None = None,
                  season: str | None = None) -> list[dict[str, Any]]:
        return svc.jobs(status=status, competition=competition, season=season)

    @app.get("/explorer/jobs/active", dependencies=_auth)
    def jobs_active() -> list[dict[str, Any]]:
        return svc.jobs_active()

    @app.get("/explorer/jobs/history", dependencies=_auth)
    def jobs_history(limit: int = 100) -> list[dict[str, Any]]:
        return svc.jobs_history(limit=limit)

    @app.get("/explorer/jobs/{job_id}", dependencies=_auth)
    def get_job(job_id: str) -> dict[str, Any]:
        job = svc.job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job

    # --- datasets / sources / AI / quality / storage ---------------------

    @app.get("/explorer/datasets", dependencies=_auth)
    def datasets() -> list[dict[str, Any]]:
        return svc.datasets()

    @app.get("/explorer/datasets/{competition}", dependencies=_auth)
    def dataset_detail(competition: str) -> dict[str, Any]:
        return svc.dataset_detail(competition)

    @app.get("/explorer/sources", dependencies=_auth)
    def sources() -> list[dict[str, Any]]:
        return svc.sources()

    @app.get("/explorer/agents", dependencies=_auth)
    def agents() -> dict[str, Any]:
        return svc.agents()

    @app.get("/explorer/langgraph", dependencies=_auth)
    def langgraph() -> dict[str, Any]:
        return svc.langgraph()

    @app.get("/explorer/qwen", dependencies=_auth)
    def qwen() -> dict[str, Any]:
        return svc.qwen()

    @app.get("/explorer/quality", dependencies=_auth)
    def quality() -> dict[str, Any]:
        return svc.quality()

    @app.get("/explorer/storage", dependencies=_auth)
    def storage() -> dict[str, Any]:
        return svc.storage()

    @app.get("/explorer/tickets", dependencies=_auth)
    def list_tickets(status: str | None = "open") -> list[dict[str, Any]]:
        return svc.tickets(status=status)

    # --- ML-D Mission Center: pipelines / executions ---------------------
    # Registration order matters: literal subpaths (catalog) must be declared
    # before the {pipeline_id} path-param route or FastAPI would match them
    # as an id.

    @app.get("/explorer/pipelines/catalog", dependencies=_auth)
    def pipelines_catalog() -> dict[str, Any]:
        return svc.pipelines_catalog()

    @app.get("/explorer/pipelines", dependencies=_auth)
    def list_pipelines() -> list[dict[str, Any]]:
        return svc.pipelines()

    @app.get("/explorer/pipelines/{pipeline_id}", dependencies=_auth)
    def get_pipeline(pipeline_id: str) -> dict[str, Any]:
        pipeline = svc.pipeline(pipeline_id)
        if pipeline is None:
            raise HTTPException(status_code=404, detail="pipeline not found")
        return pipeline

    @app.get("/explorer/executions", dependencies=_auth)
    def list_executions(pipeline_id: str | None = None, state: str | None = None) -> list[dict[str, Any]]:
        return svc.executions(pipeline_id=pipeline_id, state=state)

    @app.get("/explorer/executions/{execution_id}", dependencies=_auth)
    def get_execution(execution_id: str) -> dict[str, Any]:
        execution = svc.execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="execution not found")
        return execution

    @app.get("/explorer/executions/{execution_id}/jobs", dependencies=_auth)
    def get_execution_jobs(execution_id: str) -> list[dict[str, Any]]:
        return svc.execution_jobs(execution_id)

    @app.get("/explorer/executions/{execution_id}/dataset", dependencies=_auth)
    def get_execution_dataset(execution_id: str) -> dict[str, Any]:
        dataset = svc.execution_dataset(execution_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="execution or its pipeline not found")
        return dataset

    @app.get("/explorer/pipelines/{pipeline_id}/status", dependencies=_auth)
    def get_pipeline_realtime_status(pipeline_id: str) -> dict[str, Any]:
        if svc.pipeline(pipeline_id) is None:
            raise HTTPException(status_code=404, detail="pipeline not found")
        if app.state.collector is None:
            return {"state": "disabled", "started_at": None, "signals_captured": 0, "errors": 0,
                    "error_rate": 0.0, "last_signal_at": None, "last_error_at": None,
                    "last_error_message": None}
        return app.state.collector.status(pipeline_id)

    # --- ML-D Phase B: realtime signal sources ---------------------------

    @app.get("/explorer/realtime/sources", dependencies=_auth)
    def list_signal_sources() -> list[dict[str, Any]]:
        return svc.signal_sources()

    @app.get("/explorer/realtime/sources/{source_id}", dependencies=_auth)
    def get_signal_source(source_id: str) -> dict[str, Any]:
        source = svc.signal_source(source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="signal source not found")
        return source

    # --- ML-C quality endpoints -----------------------------------------

    @app.get("/explorer/entity-resolution", dependencies=_auth)
    def entity_resolution() -> dict[str, Any]:
        return svc.entity_resolution()

    @app.get("/explorer/duplicates", dependencies=_auth)
    def duplicates() -> dict[str, Any]:
        return svc.duplicates()

    @app.get("/explorer/quality/datasets", dependencies=_auth)
    def quality_datasets() -> dict[str, Any]:
        return svc.quality_datasets()

    @app.get("/explorer/review", dependencies=_auth)
    def review_queue(status: str = "pending", competition: str | None = None) -> dict[str, Any]:
        return svc.review_queue(status=status, competition=competition)

    @app.get("/explorer/analytics", dependencies=_auth)
    def analytics() -> dict[str, Any]:
        return svc.analytics()

    @app.get("/explorer/audit", dependencies=_auth)
    def audit(limit: int = 100) -> list[dict[str, Any]]:
        return svc.audit_log(limit=limit)

    @app.get("/explorer/metrics", dependencies=_auth)
    def get_metrics() -> Any:
        return Response(content=svc.metrics_text(), media_type="text/plain; version=0.0.4")

    # --- controls (audited) ---------------------------------------------

    def _actor(x_operator: str | None) -> str:
        return x_operator or "console"

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

    # --- ML-D Mission Center controls (audited) --------------------------

    @app.post("/explorer/pipelines/estimate", dependencies=_auth)
    def pipelines_estimate(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return svc.pipelines_estimate(body)

    @app.post("/explorer/pipelines")
    def pipelines_create(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                         x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_create(body, _actor(x_operator)))

    @app.put("/explorer/pipelines/{pipeline_id}")
    def pipelines_update(pipeline_id: str, body: dict[str, Any] = Body(...),
                         x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_update(pipeline_id, body, _actor(x_operator)))

    @app.delete("/explorer/pipelines/{pipeline_id}")
    def pipelines_delete(pipeline_id: str, x_operator: str | None = Header(None),
                         x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_delete(pipeline_id, _actor(x_operator)))

    @app.post("/explorer/pipelines/{pipeline_id}/duplicate")
    def pipelines_duplicate(pipeline_id: str, x_operator: str | None = Header(None),
                            x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_duplicate(pipeline_id, _actor(x_operator)))

    @app.post("/explorer/pipelines/{pipeline_id}/execute")
    def pipelines_execute(pipeline_id: str, x_operator: str | None = Header(None),
                          x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_execute(pipeline_id, _actor(x_operator)))

    @app.post("/explorer/executions/{execution_id}/pause")
    def executions_pause(execution_id: str, x_operator: str | None = Header(None),
                         x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().execution_pause(execution_id, _actor(x_operator)))

    @app.post("/explorer/executions/{execution_id}/resume")
    def executions_resume(execution_id: str, x_operator: str | None = Header(None),
                          x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().execution_resume(execution_id, _actor(x_operator)))

    @app.post("/explorer/executions/{execution_id}/stop")
    def executions_stop(execution_id: str, x_operator: str | None = Header(None),
                        x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().execution_stop(execution_id, _actor(x_operator)))

    # --- ML-D Phase B controls: realtime sources / pipelines (audited) ---

    @app.post("/explorer/realtime/sources")
    def signal_sources_create(body: dict[str, Any] = Body(...), x_operator: str | None = Header(None),
                              x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().signal_source_create(body, _actor(x_operator)))

    @app.put("/explorer/realtime/sources/{source_id}")
    def signal_sources_update(source_id: str, body: dict[str, Any] = Body(...),
                              x_operator: str | None = Header(None), x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().signal_source_update(source_id, body, _actor(x_operator)))

    @app.delete("/explorer/realtime/sources/{source_id}")
    def signal_sources_delete(source_id: str, x_operator: str | None = Header(None),
                              x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().signal_source_delete(source_id, _actor(x_operator)))

    @app.post("/explorer/pipelines/{pipeline_id}/start")
    def pipelines_start(pipeline_id: str, x_operator: str | None = Header(None),
                        x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_start(pipeline_id, _actor(x_operator)))

    @app.post("/explorer/pipelines/{pipeline_id}/stop")
    def pipelines_stop(pipeline_id: str, x_operator: str | None = Header(None),
                       x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_stop(pipeline_id, _actor(x_operator)))

    @app.post("/explorer/pipelines/{pipeline_id}/restart")
    def pipelines_restart(pipeline_id: str, x_operator: str | None = Header(None),
                          x_ops_token: str | None = Header(None)):
        _authorize(x_ops_token)
        return _run(lambda: controls().pipeline_restart(pipeline_id, _actor(x_operator)))

    return app
