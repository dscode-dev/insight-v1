"""Keep pgvector current with what the Explorer has collected.

    validated/ lake  →  dataset build  →  encode  →  atlas.atlas_vector_memory

WHY THIS EXISTS. Both halves of this chain already existed as scripts, and
both had to be run by hand. Nothing did, so the vector memory sat empty
while ClickHouse filled up — and an empty table is not a loud failure: every
similarity query answered successfully, with zero neighbours, and Atlas
reported low confidence rather than no data. The hot path is where the live
match reads from; it cannot depend on someone remembering.

WHY IT LIVES IN ATLAS AND NOT IN THE EXPLORER. The projection is Atlas's
feature math — walk-forward Elo, attack/defense strength, market
microstructure. Triggering this from the Explorer would put that dependency
the wrong way round: the collector would need to know how the consumer
encodes. Atlas already bind-mounts the lake, so it can watch its own input.

WHY A FINGERPRINT RATHER THAN A TIMER ALONE. A rebuild reads every record in
the lake. Running it on a fixed interval means paying that whenever nothing
has been collected, which is most intervals. The fingerprint makes the
common case a directory walk.

WHAT IT IS NOT. Not an incremental update. The projection is walk-forward:
a match inserted in the middle of the timeline changes every rating computed
after it, so a correct partial rebuild is the whole rebuild. At the current
corpus that is seconds; if it stops being seconds, the answer is to shard by
competition, not to update in place.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

ATLAS_VECTOR_REFRESH_TOTAL = Counter(
    "atlas_vector_refresh_total",
    "Vector-memory refresh passes, by outcome.",
    ["outcome"],
)
ATLAS_VECTOR_MEMORY_ROWS = Gauge(
    "atlas_vector_memory_rows",
    "Rows written by the last successful refresh, per embedding version.",
    ["embedding_version"],
)
ATLAS_VECTOR_REFRESH_COLLAPSED = Gauge(
    "atlas_vector_refresh_collapsed",
    "Duplicate source records the last build merged away. A sudden rise "
    "means a new source overlaps an existing one; a fall to zero when "
    "several sources are enabled means the merge stopped working.",
)


@dataclass(frozen=True)
class RefreshResult:
    status: str                 # "written" | "unchanged" | "empty"
    rows: int = 0
    read: int = 0
    collapsed: int = 0
    multi_source: int = 0
    score_conflicts: int = 0
    versions: tuple[str, ...] = ()
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rows": self.rows,
            "read": self.read,
            "collapsed": self.collapsed,
            "multi_source": self.multi_source,
            "score_conflicts": self.score_conflicts,
            "versions": list(self.versions),
            "detail": self.detail,
        }


def lake_fingerprint(lake_dir: Path) -> str:
    """A cheap stand-in for "has anything been collected since last time".

    Counts files, total bytes and the newest mtime. A collection either adds
    a part file or appends to one, so all three move together; none of them
    moves when the lake is idle.

    Deliberately not a content hash: hashing every record to decide whether
    to read every record saves nothing.
    """
    files = 0
    total = 0
    newest = 0.0
    if not lake_dir.exists():
        return "absent"
    for path in lake_dir.rglob("*.jsonl"):
        try:
            info = path.stat()
        except OSError:
            # A part file being rotated mid-walk. Skipping it makes the
            # fingerprint differ from the next pass's, which retries — the
            # safe direction to be wrong in.
            continue
        files += 1
        total += info.st_size
        newest = max(newest, info.st_mtime)
    return f"{files}:{total}:{newest:.0f}"


@dataclass
class VectorMemoryRefresher:
    """Registered like a watcher; produces no observations, like the janitor.

    `build` and `encode_and_upsert` are injected so the scheduling, the skip
    logic and the reporting can be tested without a lake or a database.
    """

    lake_dir: Path
    dataset_dir: Path
    build: Callable[[str, str], dict]
    encode_and_upsert: Callable[[Path, Path, str], Any]
    embedding_versions: tuple[str, ...] = ("v1", "v2")
    # `is_enabled` the field, `enabled()` the method — the Watcher protocol
    # asks for the latter, and a dataclass cannot carry both under one name.
    is_enabled: bool = True
    # Two throttles, for two different costs. This one bounds how often the
    # lake is WALKED: the shared watcher tick is 30s, and rglob over a lake
    # that only grows is not free. The fingerprint below bounds how often it
    # is REBUILT, which is the expensive half.
    min_interval_seconds: float = 1800.0
    now: Callable[[], float] = time.monotonic
    _fingerprint: str | None = field(default=None, init=False)
    _last_walk: float | None = field(default=None, init=False)

    def name(self) -> str:
        return "vector_memory_refresh"

    def enabled(self) -> bool:
        return self.is_enabled

    async def observe(self) -> list:
        await self.refresh()
        return []

    async def refresh(self, *, force: bool = False) -> RefreshResult:
        if not self.is_enabled:
            return RefreshResult(status="unchanged", detail="disabled")

        moment = self.now()
        if not force and self._last_walk is not None and (
            moment - self._last_walk < self.min_interval_seconds
        ):
            return RefreshResult(status="unchanged", detail="throttled")
        self._last_walk = moment

        fingerprint = await asyncio.to_thread(lake_fingerprint, self.lake_dir)
        if not force and fingerprint == self._fingerprint:
            ATLAS_VECTOR_REFRESH_TOTAL.labels(outcome="unchanged").inc()
            return RefreshResult(status="unchanged", detail="lake inalterado")

        try:
            result = await self._rebuild()
        except Exception as exc:
            # The fingerprint is NOT advanced: a failed pass must retry on the
            # next tick rather than record the lake as processed.
            ATLAS_VECTOR_REFRESH_TOTAL.labels(outcome="failed").inc()
            logger.exception(
                "atlas_vector_refresh_failed", extra={"error": str(exc)}
            )
            raise

        self._fingerprint = fingerprint
        return result

    async def _rebuild(self) -> RefreshResult:
        # Built beside the target and moved into place, so a crash mid-build
        # cannot leave the configured dataset path holding half a corpus —
        # which reads as a real corpus that is merely smaller.
        staging = self.dataset_dir / ".staging"
        _remove_tree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            stats = await asyncio.to_thread(
                self.build, str(self.lake_dir), str(staging)
            )
            rows = int(stats.get("rows", 0))
            if rows == 0:
                ATLAS_VECTOR_REFRESH_TOTAL.labels(outcome="empty").inc()
                logger.warning("atlas_vector_refresh_empty_dataset")
                return RefreshResult(status="empty", detail="lake sem partidas encerradas")

            matches = staging / "matches.jsonl"
            projection = staging / "projection.jsonl"

            written: list[str] = []
            for version in self.embedding_versions:
                count = await self.encode_and_upsert(matches, projection, version)
                ATLAS_VECTOR_MEMORY_ROWS.labels(embedding_version=version).set(count)
                written.append(version)

            # Published only after every version is in the database, so the
            # configured path never points at a corpus the vector memory has
            # not caught up with.
            self._publish(staging)
        finally:
            _remove_tree(staging)

        collapsed = int(stats.get("collapsed", 0))
        ATLAS_VECTOR_REFRESH_COLLAPSED.set(collapsed)
        ATLAS_VECTOR_REFRESH_TOTAL.labels(outcome="written").inc()
        logger.info(
            "atlas_vector_refresh_written",
            extra={
                "rows": rows,
                "read": int(stats.get("read", 0)),
                "collapsed": collapsed,
                "score_conflicts": int(stats.get("score_conflicts", 0)),
                "versions": written,
            },
        )
        return RefreshResult(
            status="written",
            rows=rows,
            read=int(stats.get("read", 0)),
            collapsed=collapsed,
            multi_source=int(stats.get("multi_source", 0)),
            score_conflicts=int(stats.get("score_conflicts", 0)),
            versions=tuple(written),
        )

    def _publish(self, staging: Path) -> None:
        """Move the staged dataset to `current/`, replacing what was there.

        `os.replace` will not rename a directory onto a non-empty one, so the
        previous corpus is moved aside first and deleted after the new one is
        in place — the window where `current/` does not exist is one rename
        wide, and a reader that lands in it gets a missing-file error rather
        than a truncated corpus.
        """
        target = self.dataset_dir / "current"
        previous = self.dataset_dir / "current.previous"
        _remove_tree(previous)
        if target.exists():
            os.replace(target, previous)
        os.replace(staging, target)
        _remove_tree(previous)

        # load_dataset is lru_cached on the path, and the path does not change
        # — `current/matches.jsonl` is the same string every time. Without
        # this, Atlas keeps answering from the corpus it read at boot, and the
        # refresh shows up in the database while the running process never
        # sees it. Which is the failure this whole module exists to end.
        from atlas.intelligence.historical import load_dataset

        load_dataset.cache_clear()


def _remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


def build_vector_refresher(settings, session_factory) -> VectorMemoryRefresher:
    """Wire the refresher against the real corpus builder and repository.

    Imports are local so this module stays importable without pulling in the
    intelligence package and the database layer — the tests exercise the
    scheduling and skip logic with neither.
    """
    from atlas.intelligence.corpus import build
    from atlas.vector_memory.embedding import DeterministicEmbeddingEncoder
    from atlas.vector_memory.repository import PgVectorMemoryRepository

    encoder = DeterministicEmbeddingEncoder()
    repository = PgVectorMemoryRepository(session_factory)

    async def encode_and_upsert(matches: Path, projection: Path, version: str) -> int:
        from atlas.intelligence.historical import load_dataset

        # Read from the STAGING copy, by its own path — the cached entry for
        # the published path still holds the previous corpus at this point,
        # and encoding that would write vectors for the dataset being
        # replaced.
        dataset = load_dataset(str(matches), str(projection))
        is_v2 = version == "v2"
        encode = encoder.from_record_v2 if is_v2 else encoder.from_record
        upsert = repository.upsert_many_v2 if is_v2 else repository.upsert_many

        total = 0
        batch = []
        for record in dataset.records:
            batch.append(encode(record))
            if len(batch) >= 500:
                total += await upsert(batch)
                batch = []
        if batch:
            total += await upsert(batch)
        return total

    # The lake root holds raw/ normalized/ validated/ side by side; only the
    # validated layer is a corpus. Same caveat StrengthSyncWatcher carries.
    lake = Path(settings.explorer_data_root.rstrip("/")) / "validated"
    return VectorMemoryRefresher(
        lake_dir=lake,
        dataset_dir=Path(settings.vector_refresh_dataset_dir),
        build=build,
        encode_and_upsert=encode_and_upsert,
        is_enabled=settings.vector_refresh_enabled,
        min_interval_seconds=settings.vector_refresh_min_interval_seconds,
    )
