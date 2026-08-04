"""SignalSource CRUD store — one JSON file per source under
`reports/realtime_sources/{id}.json`. Same atomic-write + retry + lock
discipline as `explorer/pipelines/store.py`. `api_key` is stored in plain
JSON like everything else in the lake (no at-rest encryption in V1 — a known
limitation, not solved here) but is NEVER returned by `list()`/`get()`,
which always hand back `to_public_dict()`.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from explorer.config import DATA_LAKE_ROOT
from explorer.realtime.models import SignalSource

_LOCK = threading.Lock()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _retry_on_transient_os_error(fn, attempts: int = 8, delay_s: float = 0.02):
    """A reader/writer can transiently race another thread's atomic rename
    (observed on Windows; not on the Linux containers this service runs on)."""
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


class SignalSourceNotFound(KeyError):
    pass


class SignalSourceStore:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)
        self.dir = self.root / "reports" / "realtime_sources"

    def _path(self, source_id: str) -> Path:
        return self.dir / f"{source_id}.json"

    def _write(self, source: SignalSource) -> None:
        with _LOCK:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self._path(source.source_id)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(source.to_dict(), ensure_ascii=False, indent=2), "utf-8")
            _retry_on_transient_os_error(lambda: tmp.replace(path))

    def _load(self, path: Path) -> SignalSource:
        return SignalSource.from_dict(json.loads(_read_text_with_retry(path)))

    def list(self) -> list[SignalSource]:
        if not self.dir.exists():
            return []
        out = []
        for f in sorted(self.dir.glob("*.json")):
            try:
                out.append(self._load(f))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def get(self, source_id: str) -> SignalSource:
        path = self._path(source_id)
        if not path.exists():
            raise SignalSourceNotFound(source_id)
        return self._load(path)

    def create(self, source: SignalSource) -> SignalSource:
        source.created_at = source.created_at or _now()
        source.updated_at = _now()
        self._write(source)
        return source

    def update(self, source_id: str, **changes) -> SignalSource:
        """`api_key` is only overwritten when explicitly present in
        `changes` — a PUT that omits it (the normal case, since GET never
        echoes the raw value back) preserves the existing key."""
        existing = self.get(source_id)
        merged = existing.to_dict()
        merged.update(changes)
        merged["source_id"] = source_id
        merged["updated_at"] = _now()
        updated = SignalSource.from_dict(merged)
        self._write(updated)
        return updated

    def delete(self, source_id: str) -> None:
        path = self._path(source_id)
        if not path.exists():
            raise SignalSourceNotFound(source_id)
        with _LOCK:
            path.unlink()
