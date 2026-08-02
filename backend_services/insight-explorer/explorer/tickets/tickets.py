"""Explorer ticket model + store (Step 12, shape from ML_A_ERROR_MANAGEMENT).

Tickets are written to reports/tickets/ as JSONL (append-only audit) and
deduplicated by (source, competition, season, entity_type, error_type):
a repeat increments `occurrences` instead of opening a new ticket. A ticket
NEVER interrupts the run — the caller records it and continues.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from explorer.config import DATA_LAKE_ROOT

ERROR_TYPES = {
    "source_offline",
    "collector_crash",
    "layout_changed",
    "validation_threshold",
    "mass_duplication",
    "data_inconsistent",
    "job_repeated_failure",
    "ai_runtime_unavailable",  # Step 8 — local Qwen unreachable
    "entity_unresolved",       # Step 7 — team not in Club Registry
}

SUGGESTED_ACTION = {
    "source_offline": "check connectivity/credentials; back off; verify provider status",
    "collector_crash": "inspect stack in the job log (job_id); pin parser version",
    "layout_changed": "diff raw/ artifact vs last good; update selectors; bump parser version",
    "validation_threshold": "inspect top explorer_validation_errors_total{rule}; fix mapper",
    "mass_duplication": "verify dedup key (provenance.checksum); check pagination loop",
    "data_inconsistent": "reconcile events vs score; prefer higher-trust source; human review",
    "job_repeated_failure": "inspect consecutive failures for this key; check source + parser",
    "ai_runtime_unavailable": "start Ollama + pull the Qwen model on the GPU host; rerun job",
    "entity_unresolved": "add the club/alias to the Club Registry; rerun entity resolution",
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Ticket:
    severity: str
    source: str
    competition: str
    season: str
    entity_type: str
    error_type: str
    suggested_action: str
    sample_payload: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    status: str = "open"
    occurrences: int = 1
    ticket_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    first_seen_at: str = field(default_factory=_now)
    last_seen_at: str = field(default_factory=_now)

    def key(self) -> tuple[str, ...]:
        return (self.source, self.competition, self.season, self.entity_type, self.error_type)


class TicketStore:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.dir = Path(root) / "reports" / "tickets"
        self._by_key: dict[tuple[str, ...], Ticket] = {}

    def open(
        self,
        *,
        error_type: str,
        source: str,
        competition: str,
        season: str,
        entity_type: str,
        severity: str = "medium",
        sample_payload: dict[str, Any] | None = None,
        retry_count: int = 0,
    ) -> Ticket:
        if error_type not in ERROR_TYPES:
            raise ValueError(f"unknown error_type: {error_type!r}")
        probe = Ticket(
            severity=severity, source=source, competition=competition, season=season,
            entity_type=entity_type, error_type=error_type,
            suggested_action=SUGGESTED_ACTION[error_type],
            sample_payload=_truncate(sample_payload or {}), retry_count=retry_count,
        )
        existing = self._by_key.get(probe.key())
        if existing:
            existing.occurrences += 1
            existing.last_seen_at = _now()
            existing.retry_count = max(existing.retry_count, retry_count)
            return existing
        self._by_key[probe.key()] = probe
        return probe

    def all(self) -> list[Ticket]:
        return list(self._by_key.values())

    def flush(self) -> Path | None:
        """Persist current tickets as a JSONL snapshot (append-only audit)."""
        if not self._by_key:
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"tickets-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for t in self._by_key.values():
                fh.write(json.dumps(asdict(t), ensure_ascii=False, default=str) + "\n")
        return path


def _truncate(payload: dict[str, Any], limit: int = 1500) -> dict[str, Any]:
    blob = json.dumps(payload, ensure_ascii=False, default=str)
    if len(blob) <= limit:
        return payload
    return {"_truncated": True, "preview": blob[:limit]}
