"""Layered, append-only, replay-safe JSONL data lake (Step 4).

Layout:
    {root}/{layer}/{competition}/{season}/{source}/{entity_type}/*.jsonl

Layers: raw, normalized, validated, training, exports, reports.

- **Append-only**: writers append JSONL lines; nothing is mutated in place.
- **Replay-safe**: each line is keyed by a content checksum; re-running a
  job does not duplicate lines (the writer skips checksums already present
  in the target file's index).
- **Checksum-aware**: `checksum()` is the canonical content hash used both
  for replay-safety and for dedup (Step 9).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from explorer.config import DATA_LAKE_ROOT, LAKE_LAYERS


def checksum(obj: Any) -> str:
    """Stable sha256 over canonical JSON. Used for dedup + replay safety."""
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DataLake:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)

    # --- pathing ---------------------------------------------------------

    def partition(
        self, layer: str, competition: str, season: str, source: str, entity_type: str
    ) -> Path:
        if layer not in LAKE_LAYERS:
            raise ValueError(f"unknown lake layer: {layer!r}")
        return self.root / layer / competition / season / source / entity_type

    def _file(self, layer: str, competition: str, season: str, source: str, entity_type: str) -> Path:
        d = self.partition(layer, competition, season, source, entity_type)
        d.mkdir(parents=True, exist_ok=True)
        return d / "part-0001.jsonl"

    # --- index for replay safety ----------------------------------------

    @staticmethod
    def _existing_checksums(path: Path) -> set[str]:
        seen: set[str] = set()
        if not path.exists():
            return seen
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cs = rec.get("_checksum")
                if cs:
                    seen.add(cs)
        return seen

    # --- writes ----------------------------------------------------------

    def append(
        self,
        layer: str,
        competition: str,
        season: str,
        source: str,
        entity_type: str,
        records: Iterable[dict[str, Any]],
    ) -> dict[str, int]:
        """Append records as JSONL. Returns {written, skipped}. Each record
        is wrapped with its `_checksum`; lines whose checksum already exists
        in the target file are skipped (replay-safe)."""
        path = self._file(layer, competition, season, source, entity_type)
        seen = self._existing_checksums(path)
        written = skipped = 0
        with path.open("a", encoding="utf-8") as fh:
            for rec in records:
                cs = rec.get("_checksum") or checksum(rec)
                if cs in seen:
                    skipped += 1
                    continue
                seen.add(cs)
                line = dict(rec)
                line["_checksum"] = cs
                fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
                written += 1
        return {"written": written, "skipped": skipped}

    # --- reads -----------------------------------------------------------

    def read(
        self, layer: str, competition: str, season: str, source: str, entity_type: str
    ) -> Iterator[dict[str, Any]]:
        path = self._file(layer, competition, season, source, entity_type)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def write_report(self, *parts: str, payload: Any) -> Path:
        """Write a JSON report under reports/ (rejected, tickets, summaries)."""
        d = self.root / "reports"
        for p in parts[:-1]:
            d = d / p
        d.mkdir(parents=True, exist_ok=True)
        path = d / parts[-1]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), "utf-8")
        return path

    def append_report_lines(self, *parts: str, records: Iterable[dict[str, Any]]) -> Path:
        """Append JSONL rows under reports/ (e.g. rejected/)."""
        d = self.root / "reports"
        for p in parts[:-1]:
            d = d / p
        d.mkdir(parents=True, exist_ok=True)
        path = d / parts[-1]
        with path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return path

    # --- sizing (metrics) ------------------------------------------------

    def layer_size_bytes(self, layer: str) -> int:
        base = self.root / layer
        if not base.exists():
            return 0
        return sum(f.stat().st_size for f in base.rglob("*") if f.is_file())
