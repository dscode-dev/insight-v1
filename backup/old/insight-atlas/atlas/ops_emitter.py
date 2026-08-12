"""Operations emitter (ML-C.5e) — pushes events/tickets/runs to the Robozão
Gateway operations API. FIRE-AND-FORGET + FAIL-SAFE: any error (network, config,
gateway down) is swallowed so a long-running collection/training NEVER breaks
because observability is unavailable.

Config (env):
  OPERATIONS_GATEWAY_URL  e.g. http://robozao-gateway:8095   (empty → disabled)
  OPS_INGEST_TOKEN        shared service token (empty → disabled)
  INSIGHT_SERVICE         default service name (e.g. "atlas" / "atlas")
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

_TIMEOUT = 3.0


class OpsEmitter:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        service: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("OPERATIONS_GATEWAY_URL", "")).rstrip("/")
        self.token = token or os.environ.get("OPS_INGEST_TOKEN", "")
        self.service = service or os.environ.get("INSIGHT_SERVICE", "atlas")

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.token)

    def emit_event(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "INFO",
        run_id: str = "",
        dataset_id: str = "",
        training_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._post("/operations/events", {
            "event_type": event_type, "service": self.service, "severity": severity,
            "message": message, "run_id": run_id, "dataset_id": dataset_id,
            "training_id": training_id, "metadata": metadata or {},
        })

    def open_ticket(
        self,
        reason: str,
        *,
        severity: str = "ERROR",
        dataset: str = "",
        impact: str = "",
        recommendation: str = "",
        dedup_key: str = "",
    ) -> None:
        self._post("/operations/tickets", {
            "service": self.service, "severity": severity, "reason": reason,
            "dataset": dataset, "impact": impact, "recommendation": recommendation,
            "dedup_key": dedup_key or f"{self.service}:{dataset}:{reason}",
        })

    def upsert_run(
        self,
        run_id: str,
        kind: str,
        status: str,
        *,
        run_label: str = "",
        datasets: list[str] | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        self._post("/operations/runs", {
            "run_id": run_id, "run_label": run_label or run_id, "service": self.service,
            "kind": kind, "status": status, "datasets": datasets or [],
            "summary": summary or {},
        })

    # ---- internals (never raise) ----

    def _post(self, path: str, body: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                self.base_url + path, data=data, method="POST",
                headers={"Content-Type": "application/json", "X-Ops-Token": self.token},
            )
            with urllib.request.urlopen(req, timeout=_TIMEOUT):
                pass
        except Exception:
            # Observability must never break the work. Swallow everything.
            return


# Process-wide default emitter (config from env).
emitter = OpsEmitter()
