"""Review backlog management (ML-C Part 5).

The pipeline routes records it cannot confidently validate to a review queue
(reports/review/{competition}/{season}/{source}/queue.jsonl), preserving the
full envelope + the reason. Operators can:
  - list the queue (with reasons),
  - promote a record (write its envelope to validated/),
  - reject a record,
  - replay a whole competition/season (re-collect through the pipeline).
All mutations are audited by the caller (controls).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from explorer.config import DATA_LAKE_ROOT
from explorer.datalake.lake import DataLake

# Guards read-modify-write of queue.jsonl files against the pipeline
# concurrently appending new review records (single-container, multi-thread).
_LOCK = threading.Lock()


class ReviewStore:
    def __init__(self, root: Path | str = DATA_LAKE_ROOT) -> None:
        self.root = Path(root)
        self.base = self.root / "reports" / "review"
        self.lake = DataLake(self.root)

    def _queue_files(self) -> list[Path]:
        return sorted(self.base.rglob("queue.jsonl")) if self.base.exists() else []

    @staticmethod
    def _parts(path: Path) -> tuple[str, str, str]:
        # reports/review/{comp}/{season}/{source}/queue.jsonl
        p = path.parts
        return p[-4], p[-3], p[-2]

    def queue(self, status: str | None = "pending", competition: str | None = None,
              limit: int = 500) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for f in self._queue_files():
            comp, season, source = self._parts(f)
            if competition and comp != competition:
                continue
            for line in f.read_text("utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if status and rec.get("status", "pending") != status:
                    continue
                out.append({"competition": comp, "season": season, "source": source,
                            "external_id": rec.get("external_id"), "reason": rec.get("reason"),
                            "stage": rec.get("stage"), "quality": rec.get("quality"),
                            "status": rec.get("status", "pending")})
                if len(out) >= limit:
                    return out
        return out

    def reasons_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.queue(status="pending", limit=100000):
            counts[r["reason"] or "unknown"] = counts.get(r["reason"] or "unknown", 0) + 1
        return counts

    def _rewrite(self, f: Path, external_id: str, new_status: str) -> dict[str, Any] | None:
        with _LOCK:
            lines = f.read_text("utf-8").splitlines()
            changed = None
            out = []
            for line in lines:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("external_id") == external_id and rec.get("status", "pending") == "pending":
                    rec["status"] = new_status
                    changed = rec
                out.append(json.dumps(rec, ensure_ascii=False, default=str))
            if changed:
                tmp = f.with_suffix(".jsonl.tmp")
                tmp.write_text("\n".join(out) + "\n", "utf-8")
                tmp.replace(f)  # atomic
            return changed

    def promote(self, external_id: str) -> dict[str, Any]:
        for f in self._queue_files():
            comp, season, source = self._parts(f)
            rec = self._rewrite(f, external_id, "promoted")
            if rec:
                env = rec.get("envelope")
                if env:
                    self.lake.append("validated", comp, season, source, "fixture", [env])
                return {"promoted": external_id, "competition": comp, "season": season,
                        "source": source}
        raise KeyError(f"review record {external_id} not found / not pending")

    def reject(self, external_id: str) -> dict[str, Any]:
        for f in self._queue_files():
            comp, season, source = self._parts(f)
            rec = self._rewrite(f, external_id, "rejected")
            if rec:
                self.lake.append_report_lines(
                    "rejected", comp, season, source, "from_review.jsonl",
                    records=[{"external_id": external_id, "reason": rec.get("reason"),
                              "_class": "rejected", "from_review": True}])
                return {"rejected": external_id, "competition": comp, "season": season}
        raise KeyError(f"review record {external_id} not found / not pending")

    def stats(self) -> dict[str, Any]:
        pending = self.queue(status="pending", limit=100000)
        promoted = self.queue(status="promoted", limit=100000)
        rejected = self.queue(status="rejected", limit=100000)
        return {"pending": len(pending), "promoted": len(promoted), "rejected": len(rejected),
                "reasons": self.reasons_summary()}
