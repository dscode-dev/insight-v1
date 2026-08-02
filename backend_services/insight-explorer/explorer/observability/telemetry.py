"""Runtime telemetry stores (ML-B.6 visibility).

Append-only JSONL under the data lake `reports/telemetry/` capturing what the
AI layer actually did, so the Console can show real CrewAI / LangGraph activity
(not just counters). Three streams:

- agents.jsonl  — one row per CrewAI agent call (agent, backend, latency,
                  tokens, success, truncated input/output sample).
- graph.jsonl   — one row per LangGraph pipeline run (engine, node outcomes,
                  validated/rejected/review, duration).
- audit.jsonl   — one row per operator control action (actor, action, params).

All writes are best-effort and never raise into the pipeline.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from explorer.config import DATA_LAKE_ROOT

_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _truncate(value: Any, limit: int = 600) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"


class Telemetry:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.dir = Path(root) / "reports" / "telemetry"

    def _append(self, name: str, record: dict[str, Any]) -> None:
        try:
            with _LOCK:
                self.dir.mkdir(parents=True, exist_ok=True)
                with (self.dir / name).open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception:  # noqa: BLE001 - telemetry must never break the pipeline
            pass

    # --- writers ---------------------------------------------------------

    def agent_call(self, *, agent: str, backend: str, latency_s: float, prompt_tokens: int,
                   completion_tokens: int, success: bool, competition: str = "", season: str = "",
                   sample_input: Any = "", sample_output: Any = "", error: str = "") -> None:
        self._append("agents.jsonl", {
            "ts": _now(), "agent": agent, "backend": backend,
            "latency_s": round(latency_s, 3), "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "success": success,
            "competition": competition, "season": season,
            "sample_input": _truncate(sample_input), "sample_output": _truncate(sample_output),
            "error": _truncate(error, 200),
        })

    def graph_run(self, *, run_id: str, competition: str, season: str, source: str, engine: str,
                  nodes: list[str], validated: int, rejected: int, review: int,
                  duration_s: float, outcome: str) -> None:
        self._append("graph.jsonl", {
            "ts": _now(), "run_id": run_id, "competition": competition, "season": season,
            "source": source, "engine": engine, "nodes": nodes, "validated": validated,
            "rejected": rejected, "review": review, "duration_s": round(duration_s, 3),
            "outcome": outcome,
        })

    def audit(self, *, actor: str, action: str, params: dict[str, Any], result: str) -> None:
        self._append("audit.jsonl", {
            "ts": _now(), "actor": actor, "action": action, "params": params, "result": result,
        })

    # --- readers (tail-bounded) -----------------------------------------

    def read(self, name: str, limit: int | None = None) -> list[dict[str, Any]]:
        path = self.dir / name
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows[-limit:] if limit else rows
