"""Operational Replay Service (ATLAS-BACKTEST-A2, Stages 4-6, 8).

Runs replay scenarios as background asyncio jobs (never blocks Atlas runtime),
tracks a deterministic lifecycle (submitted → queued → running → completed |
failed | cancelled), persists reproducible artifacts, and emits canonical IOC
operational events through the EXISTING event contract (OperationalEventBus) —
no new telemetry model.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from atlas.backtest.contracts import (
    QualityEvaluation,
    ReplayArtifacts,
    ReplayExecution,
    ReplayReport,
    ReplayResult,
    ReplayScenario,
)
from atlas.backtest.engine import ReplayEngine
from atlas.backtest.manifest import ReplayManifest, build_manifest
from atlas.backtest.quality import evaluate


class OperationalEmitter(Protocol):
    def emit(self, event_type: str, **kwargs: Any) -> Any: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReplayService:
    def __init__(
        self,
        engine: ReplayEngine | None = None,
        *,
        events: OperationalEmitter | None = None,
        baseline: ReplayResult | None = None,
    ) -> None:
        self._engine = engine if engine is not None else ReplayEngine()
        self._events = events
        self._baseline = baseline  # optional regression/quality reference
        self._executions: dict[str, ReplayExecution] = {}
        self._artifacts: dict[str, ReplayArtifacts] = {}
        self._manifests: dict[str, ReplayManifest] = {}
        self._quality: dict[str, QualityEvaluation] = {}
        self._event_log: dict[str, list[dict]] = {}
        self._order: list[str] = []

    # -- submission -----------------------------------------------------------

    def submit(
        self,
        scenario: ReplayScenario,
        *,
        dataset_id: str = "",
        requester: str = "",
    ) -> ReplayExecution:
        execution = self._register(scenario, dataset_id=dataset_id, requester=requester)
        asyncio.ensure_future(self._run(execution.execution_id, scenario))
        return execution

    async def run_now(
        self,
        scenario: ReplayScenario,
        *,
        dataset_id: str = "",
        requester: str = "",
    ) -> ReplayExecution:
        execution = self._register(scenario, dataset_id=dataset_id, requester=requester)
        await self._run(execution.execution_id, scenario)
        return self._executions[execution.execution_id]

    def _register(
        self, scenario: ReplayScenario, *, dataset_id: str, requester: str
    ) -> ReplayExecution:
        execution_id = str(uuid.uuid4())
        execution = ReplayExecution(
            execution_id=execution_id,
            scenario_id=scenario.scenario_id,
            source=scenario.source,
            status="submitted",
            dataset_id=dataset_id,
            requester=requester,
            submitted_at=_now(),
        )
        self._executions[execution_id] = execution
        self._event_log[execution_id] = []
        self._order.append(execution_id)
        self._emit(execution_id, "replay_submitted", current_state="submitted")
        return execution

    # -- execution ------------------------------------------------------------

    async def _run(self, execution_id: str, scenario: ReplayScenario) -> None:
        if self._executions[execution_id].status == "cancelled":
            return
        self._patch(execution_id, status="queued", queued_at=_now())
        self._emit(execution_id, "replay_started", current_state="running")
        started = _now()
        self._patch(execution_id, status="running", started_at=started)
        try:
            self._emit(execution_id, "dataset_loaded", current_state="running")
            self._emit(execution_id, "trend_generation_started", stage="trend_generation")
            result = await self._engine.run(scenario)
            self._emit(execution_id, "trend_generation_finished", stage="trend_generation")

            artifacts = ReplayArtifacts(
                execution_id=execution_id,
                replay_hash=result.deterministic_hash,
                report=result.report,
                detectors=result.detectors,
                trend_timeline=result.report.trend_timeline,
                operational_events=list(self._event_log[execution_id]),
            )
            self._artifacts[execution_id] = artifacts
            self._emit(execution_id, "report_generated", current_state="running")

            # ATLAS-BACKTEST-B — Quality Gate + reproducibility manifest.
            self._emit(execution_id, "replay_quality_started", stage="quality")
            quality = evaluate(result, baseline=self._baseline)
            self._quality[execution_id] = quality
            self._emit(execution_id, "detector_evaluated",
                      metadata={"detectors": len(quality.detectors)})
            self._emit(execution_id, "quality_metrics_generated", stage="quality")
            self._emit(execution_id, "promotion_report_generated",
                      metadata={"promotions": len(quality.promotions)})
            if quality.regression is not None and quality.regression.quality_regression:
                self._emit(execution_id, "regression_detected", severity="WARNING",
                          stage="quality")
            self._emit(execution_id, "replay_quality_completed", stage="quality")

            finished = _now()
            self._manifests[execution_id] = build_manifest(
                replay_id=execution_id,
                replay_hash=result.deterministic_hash,
                dataset=scenario.scenario_id,
                execution_timestamp=finished,
                execution_duration_ms=int((finished - started).total_seconds() * 1000),
                artifact_locations=["report", "detectors", "quality", "manifest"],
            )
            self._patch(
                execution_id,
                status="completed",
                finished_at=finished,
                duration_ms=int((finished - started).total_seconds() * 1000),
                replay_hash=result.deterministic_hash,
                artifact_keys=["report", "detectors", "trend_timeline", "operational_events"],
                result=result,
            )
            self._emit(execution_id, "replay_completed", current_state="completed")
        except Exception as exc:  # noqa: BLE001 — replay must never crash the runtime
            finished = _now()
            self._patch(
                execution_id,
                status="failed",
                finished_at=finished,
                duration_ms=int((finished - started).total_seconds() * 1000),
                error=str(exc),
            )
            self._emit(execution_id, "replay_failed", severity="ERROR", current_state="failed")

    # -- lifecycle control ----------------------------------------------------

    def cancel(self, execution_id: str) -> ReplayExecution | None:
        execution = self._executions.get(execution_id)
        if execution is None or execution.status in {"completed", "failed", "cancelled"}:
            return execution
        self._patch(execution_id, status="cancelled", finished_at=_now())
        self._emit(execution_id, "replay_failed", current_state="cancelled")
        return self._executions[execution_id]

    # -- reads ----------------------------------------------------------------

    def status(self, execution_id: str) -> ReplayExecution | None:
        return self._executions.get(execution_id)

    def history(self, *, limit: int = 50) -> list[ReplayExecution]:
        return [self._executions[i] for i in reversed(self._order[-limit:])]

    def report(self, execution_id: str) -> ReplayReport | None:
        artifacts = self._artifacts.get(execution_id)
        return artifacts.report if artifacts else None

    def artifacts(self, execution_id: str) -> ReplayArtifacts | None:
        return self._artifacts.get(execution_id)

    def manifest(self, execution_id: str) -> ReplayManifest | None:
        return self._manifests.get(execution_id)

    def quality(self, execution_id: str) -> QualityEvaluation | None:
        return self._quality.get(execution_id)

    # -- internals ------------------------------------------------------------

    def _patch(self, execution_id: str, **fields: Any) -> None:
        self._executions[execution_id] = self._executions[execution_id].model_copy(
            update=fields
        )

    def _emit(self, execution_id: str, event_type: str, **kwargs: Any) -> None:
        execution = self._executions[execution_id]
        payload = {
            "event_type": event_type,
            "correlation_id": execution_id,
            "dataset_id": execution.dataset_id,
            **kwargs,
        }
        self._event_log[execution_id].append(payload)
        if self._events is not None:
            try:
                self._events.emit(event_type, correlation_id=execution_id,
                                  dataset_id=execution.dataset_id, **kwargs)
            except Exception:  # noqa: BLE001 — telemetry must never break replay
                pass
