"""Execution domain model — one run of a `Pipeline` (ML-D Mission Center).

Field names match what the Console's already-built UI reads
(`data-intelligence-center.tsx`'s `Executions`/`PipelineCard`,
`execution-detail.tsx`) so that UI starts working against a real backend
without needing its own changes.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

EXECUTION_STATES = ("pending", "running", "paused", "completed", "failed", "stopped")


@dataclass
class Execution:
    pipeline_id: str
    pipeline_name: str = ""
    state: str = "pending"
    progress: float = 0.0
    jobs_completed: int = 0
    jobs_total: int = 0
    jobs_remaining: int = 0
    records: int = 0
    source_count: int = 0
    failed_source_jobs: int = 0
    retries: int = 0
    duration_seconds: float = 0.0
    eta_seconds: float | None = None
    throughput_records_per_second: float = 0.0
    source_contribution: dict[str, int] = field(default_factory=dict)
    atlas_ingestion: dict[str, Any] = field(default_factory=lambda: {"status": "not_started"})
    generation: str = ""
    # Why a `failed` execution failed. Empty on every other state.
    #
    # Without it a crashed execution could only say "failed", and the reason
    # lived in a stack trace scrolling past among access logs. The console
    # shows this string, so the first question an operator asks is answered
    # on the screen they are already looking at.
    error: str = ""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = ""
    started_at: str = ""
    ended_at: str = ""
    # Decomposed work items: [{"competition": ..., "season": ..., "status": "pending"|"done"|"failed", ...}]
    tasks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Execution":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})
