"""Real-time signal domain model (ML-D Phase B).

`SignalSource` is an operator-managed connector (public API, RSS, private
API needing a key, or a crawler/scraper) — reusable across multiple
`Pipeline(type="realtime")` records, the same way historical pipelines
reference the fixed fixture-adapter names. `CapturedSignal` is one captured
record, persisted to the `signals/` lake layer and (best-effort) published
to Atlas — see explorer/realtime/{collector,publisher}.py.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

SOURCE_KINDS = ("api", "rss", "crawler", "webhook", "noop")
SOURCE_VISIBILITY = ("public", "private")
SOURCE_STATUSES = ("healthy", "degraded", "offline", "unconfigured")
SIGNAL_TYPES = ("injury", "transfer", "news", "sentiment", "other")


def _default_metrics() -> dict[str, Any]:
    return {
        "signals_captured": 0,   # cumulative count of individual signals captured
        "poll_successes": 0,     # cumulative count of successful poll() calls
        "errors": 0,             # cumulative count of failed poll() calls
        "success_rate": None,    # poll_successes / (poll_successes + errors)
        "avg_latency_ms": None,  # average poll() latency, successful polls only
        "last_success_at": None,
        "last_error_at": None,
        "last_error_message": None,
    }


@dataclass
class SignalSource:
    name: str
    kind: str = "noop"
    visibility: str = "public"
    endpoint_url: str = ""
    api_key: str | None = None
    poll_interval_s: int = 300
    scope: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    status: str = "unconfigured"
    metrics: dict[str, Any] = field(default_factory=_default_metrics)
    source_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        """Never echoes the raw api_key back — only whether one is set."""
        d = self.to_dict()
        d["api_key_set"] = bool(d.pop("api_key", None))
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalSource":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class CapturedSignal:
    signal_type: str
    source_id: str
    text: str
    schema_version: str = "explorer.signal.v1"
    entity_refs: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.5
    published_at: str = ""
    captured_at: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
