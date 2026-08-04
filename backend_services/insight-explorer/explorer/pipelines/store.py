"""Pipeline CRUD store — one JSON file per pipeline under
`reports/pipelines/{id}.json`. Atomic writes (temp+rename) + a module lock,
same discipline as `explorer/ops/runtime_config.py` and the fixed
`explorer/ops/review.py`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from explorer.config import DATA_LAKE_ROOT
from explorer.pipelines.models import Pipeline

_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _retry_on_transient_os_error(fn, attempts: int = 8, delay_s: float = 0.02):
    """See explorer/pipelines/executions/store.py's copy of this helper for
    why: a reader/writer can transiently race another thread's atomic rename."""
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


class PipelineNotFound(KeyError):
    pass


class PipelineStore:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)
        self.dir = self.root / "reports" / "pipelines"

    def _path(self, pipeline_id: str) -> Path:
        return self.dir / f"{pipeline_id}.json"

    def _write(self, pipeline: Pipeline) -> None:
        with _LOCK:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self._path(pipeline.pipeline_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(pipeline.to_dict(), ensure_ascii=False, indent=2), "utf-8")
            _retry_on_transient_os_error(lambda: tmp.replace(path))

    def list(self) -> list[Pipeline]:
        if not self.dir.exists():
            return []
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(Pipeline.from_dict(json.loads(_read_text_with_retry(f))))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def get(self, pipeline_id: str) -> Pipeline:
        path = self._path(pipeline_id)
        if not path.exists():
            raise PipelineNotFound(pipeline_id)
        return Pipeline.from_dict(json.loads(_read_text_with_retry(path)))

    def create(self, pipeline: Pipeline) -> Pipeline:
        pipeline.created_at = pipeline.created_at or _now()
        pipeline.updated_at = _now()
        self._write(pipeline)
        return pipeline

    def update(self, pipeline_id: str, **changes) -> Pipeline:
        existing = self.get(pipeline_id)
        merged = existing.to_dict()
        merged.update(changes)
        merged["pipeline_id"] = pipeline_id
        merged["version"] = int(existing.version) + 1
        merged["updated_at"] = _now()
        updated = Pipeline.from_dict(merged)
        self._write(updated)
        return updated

    def delete(self, pipeline_id: str) -> None:
        path = self._path(pipeline_id)
        if not path.exists():
            raise PipelineNotFound(pipeline_id)
        with _LOCK:
            path.unlink()

    def duplicate(self, pipeline_id: str) -> Pipeline:
        source = self.get(pipeline_id)
        clone_dict = source.to_dict()
        clone_dict.pop("pipeline_id", None)
        clone_dict["name"] = f"{source.name} (copy)"
        clone_dict["revision_of"] = pipeline_id
        clone_dict["version"] = 1
        clone_dict["created_at"] = ""
        clone = Pipeline.from_dict(clone_dict)
        return self.create(clone)
