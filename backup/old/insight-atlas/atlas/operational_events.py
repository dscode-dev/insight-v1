"""Canonical operational event bus for Atlas.

Atlas uses the same versioned envelope as Explorer.  The envelope is carried in
operations-event metadata, preserving the existing Gateway API while giving IOC
a stable event stream contract.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from datetime import date, datetime
from typing import Any

from atlas.ops_emitter import emitter

SCHEMA_VERSION = "insight.operational_event.v1"


class OperationalEventBus:
    def __init__(self, service: str = "atlas") -> None:
        self.service = service
        self.environment = os.getenv("INSIGHT_ENV", os.getenv("ENVIRONMENT", "production"))
        self.infrastructure = os.getenv("INSIGHT_INFRASTRUCTURE", "robozao")
        self.host = os.getenv("HOSTNAME", socket.gethostname())

    def emit(
        self,
        event_type: str,
        *,
        message: str | None = None,
        severity: str = "INFO",
        mission_id: str = "",
        job_id: str = "",
        worker_id: str = "",
        correlation_id: str = "",
        previous_state: str = "",
        current_state: str = "",
        duration_ms: int | None = None,
        dataset_id: str = "",
        competition: str = "",
        season: str = "",
        provider: str = "",
        stage: str = "",
        batch_id: str = "",
        signal_batch_id: str = "",
        report_id: str = "",
        operator_id: str = "",
        progress: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_metadata = _json_safe(metadata or {})
        safe_progress = _json_safe(progress or {})
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "event_id": str(uuid.uuid4()),
            "timestamp": _now(),
            "service": self.service,
            "environment": self.environment,
            "host": self.host,
            "infrastructure": self.infrastructure,
            "severity": severity.upper(),
            "event_type": event_type,
            "mission_id": mission_id,
            "job_id": job_id,
            "worker_id": worker_id,
            "correlation_id": correlation_id or mission_id or job_id,
            "previous_state": previous_state,
            "current_state": current_state,
            "duration_ms": duration_ms,
            "competition": competition,
            "season": season,
            "provider": provider,
            "stage": stage,
            "dataset_id": dataset_id,
            "batch_id": batch_id,
            "signal_batch_id": signal_batch_id,
            "report_id": report_id,
            "operator_id": operator_id,
            "progress": safe_progress,
            "metadata": safe_metadata,
        }
        emitter.emit_event(
            event_type,
            message or event_type.replace("_", " "),
            severity=severity.upper(),
            run_id=mission_id,
            dataset_id=dataset_id,
            metadata={
                **safe_metadata,
                "operational_event": envelope,
            },
        )
        return envelope

    def emit_stage(
        self,
        stage: str,
        *,
        mission_id: str = "",
        job_id: str = "",
        previous_state: str = "",
        current_state: str = "",
        metadata: dict[str, Any] | None = None,
        **context: Any,
    ) -> dict[str, Any]:
        return self.emit(
            "execution_stage_changed",
            mission_id=mission_id,
            job_id=job_id,
            previous_state=previous_state,
            current_state=current_state or stage,
            stage=stage,
            metadata=metadata,
            **context,
        )

    def emit_progress(
        self,
        *,
        mission_id: str = "",
        job_id: str = "",
        stage: str = "",
        progress: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        **context: Any,
    ) -> dict[str, Any]:
        return self.emit(
            "execution_progress_updated",
            mission_id=mission_id,
            job_id=job_id,
            current_state="progress",
            stage=stage,
            progress=progress,
            metadata=metadata,
            **context,
        )

    def emit_diagnostic(
        self,
        diagnostic: str,
        *,
        severity: str = "WARN",
        mission_id: str = "",
        job_id: str = "",
        current_state: str = "diagnostic",
        metadata: dict[str, Any] | None = None,
        **context: Any,
    ) -> dict[str, Any]:
        return self.emit(
            diagnostic,
            severity=severity,
            mission_id=mission_id,
            job_id=job_id,
            current_state=current_state,
            metadata=metadata,
            **context,
        )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


event_bus = OperationalEventBus()
