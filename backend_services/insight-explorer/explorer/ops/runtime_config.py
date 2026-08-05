"""Mutable runtime config (ML-B.6 controls).

Persisted to the data lake so operator actions (disable a source, pause the
scheduler) survive restarts and are shared between the API and scheduler
threads in the single container. Small, JSON, atomic writes.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from explorer.config import DATA_LAKE_ROOT

_LOCK = threading.Lock()


@dataclass
class RuntimeConfig:
    disabled_sources: list[str] = field(default_factory=list)
    scheduler_paused: bool = False
    use_ai: bool = True
    # Operator-set collection priority per source name. Absent = default.
    # Lower number = higher priority, matching the usual scheduling
    # convention. `load()` already drops unknown keys, so adding this
    # field cannot disturb an existing on-disk config.
    source_priority: dict[str, int] = field(default_factory=dict)

    def source_enabled(self, name: str) -> bool:
        return name not in self.disabled_sources

    def priority_for(self, name: str, default: int = 100) -> int:
        return self.source_priority.get(name, default)


def _path(root: Path | str = DATA_LAKE_ROOT) -> Path:
    return Path(root) / "reports" / "runtime_config.json"


def load(root: Path | str = DATA_LAKE_ROOT) -> RuntimeConfig:
    p = _path(root)
    if p.exists():
        try:
            raw = json.loads(p.read_text("utf-8"))
        except json.JSONDecodeError:
            return RuntimeConfig()
        # Drop unknown keys instead of failing closed-to-defaults: a schema
        # change (new field) must not silently re-enable previously
        # operator-disabled sources or un-pause the scheduler on next deploy.
        known = {f.name for f in fields(RuntimeConfig)}
        return RuntimeConfig(**{k: v for k, v in raw.items() if k in known})
    return RuntimeConfig()


def save(cfg: RuntimeConfig, root: Path | str = DATA_LAKE_ROOT) -> None:
    p = _path(root)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), "utf-8")
        tmp.replace(p)
