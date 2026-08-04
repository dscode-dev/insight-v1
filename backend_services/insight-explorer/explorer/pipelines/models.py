"""Pipeline domain model (ML-D Mission Center).

A `Pipeline` is an operator-managed collection mission. `type` discriminates
two shapes sharing one resource: `historical` (a finite/recurring collection
scope run through the existing JobRunner/multi-source machinery) and
`realtime` (an always-on signal collector, added alongside the realtime
framework). Historical-only fields are irrelevant (left at defaults) on a
realtime pipeline and vice versa — kept as one dataclass rather than two so
the Console's list/detail views render both through one shape, matching how
the existing (pre-built) Console UI already reads pipeline rows.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

PIPELINE_TYPES = ("historical", "realtime")


@dataclass
class PipelineSource:
    name: str
    enabled: bool = True
    weight: float = 1.0
    priority: int = 1


@dataclass
class Pipeline:
    name: str
    description: str = ""
    type: str = "historical"
    owner: str = ""
    version: int = 1
    revision_of: str | None = None
    enabled: bool = True

    # --- historical fields -------------------------------------------------
    sources: list[PipelineSource] = field(default_factory=list)
    competitions: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    duration: dict[str, Any] = field(default_factory=lambda: {"mode": "one-shot"})
    schedule: str | None = None
    estimate: dict[str, Any] = field(default_factory=dict)

    # --- realtime fields (Phase B) ------------------------------------------
    signal_source_ids: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)

    pipeline_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [asdict(s) if isinstance(s, PipelineSource) else s for s in self.sources]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pipeline":
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        sources = clean.get("sources") or []
        clean["sources"] = [PipelineSource(**s) if isinstance(s, dict) else s for s in sources]
        return cls(**clean)
