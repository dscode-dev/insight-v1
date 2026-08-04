"""Execution CRUD store — one JSON file per execution under
`reports/executions/{id}.json`. Same atomic-write + lock discipline as
`explorer/pipelines/store.py`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from explorer.config import DATA_LAKE_ROOT
from explorer.pipelines.executions.models import Execution

_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _retry_on_transient_os_error(fn, attempts: int = 8, delay_s: float = 0.02):
    """A reader/writer can race another thread's atomic temp-file rename; on
    some filesystems (observed on Windows — antivirus real-time scanning
    transiently opens a just-written file — not on the Linux containers this
    service actually runs on) that raises a transient PermissionError.
    Retried briefly rather than propagated, since the underlying write is
    already atomic and the condition always clears within a few ms."""
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except (PermissionError, OSError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(delay_s)
    raise last  # pragma: no cover - only reached if the condition never clears


def _read_text_with_retry(path: Path) -> str:
    return _retry_on_transient_os_error(lambda: path.read_text("utf-8"))


class ExecutionNotFound(KeyError):
    pass


class ExecutionStore:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)
        self.dir = self.root / "reports" / "executions"

    def _path(self, execution_id: str) -> Path:
        return self.dir / f"{execution_id}.json"

    def _write(self, execution: Execution) -> None:
        with _LOCK:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self._path(execution.execution_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(execution.to_dict(), ensure_ascii=False, indent=2), "utf-8")
            _retry_on_transient_os_error(lambda: tmp.replace(path))

    def list(self, pipeline_id: str | None = None, state: str | None = None) -> list[Execution]:
        if not self.dir.exists():
            return []
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                execution = Execution.from_dict(json.loads(_read_text_with_retry(f)))
            except (json.JSONDecodeError, TypeError):
                continue
            if pipeline_id and execution.pipeline_id != pipeline_id:
                continue
            if state and execution.state != state:
                continue
            out.append(execution)
        return out

    def get(self, execution_id: str) -> Execution:
        path = self._path(execution_id)
        if not path.exists():
            raise ExecutionNotFound(execution_id)
        return Execution.from_dict(json.loads(_read_text_with_retry(path)))

    def create(self, execution: Execution) -> Execution:
        execution.created_at = execution.created_at or _now()
        self._write(execution)
        return execution

    def save(self, execution: Execution) -> Execution:
        """Persist an already-loaded (and mutated in-memory) Execution."""
        self._write(execution)
        return execution

    def update(self, execution_id: str, **changes) -> Execution:
        existing = self.get(execution_id)
        merged = existing.to_dict()
        merged.update(changes)
        merged["execution_id"] = execution_id
        updated = Execution.from_dict(merged)
        self._write(updated)
        return updated
