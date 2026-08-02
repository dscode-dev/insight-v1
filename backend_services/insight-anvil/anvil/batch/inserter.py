"""Buffered ClickHouse inserter.

Why a buffer at all? ClickHouse's insert throughput is much higher in
batches; per-row inserts pessimise the merge pipeline. So Anvil queues rows
in memory and flushes when:

  * a per-table cap is reached (`per_table_cap`),
  * the cumulative cross-table size hits `max_rows`,
  * or `max_age` seconds have elapsed since the buffer was last flushed.

Whichever fires first.

Concurrency model
-----------------
The inserter is used from a single asyncio task (the consumer's handler
runs sequentially), so we do not need a Lock for the buffer itself. The
periodic flush timer runs as a background task and acquires the same
asyncio.Lock that the synchronous flush path uses, so the two cannot
interleave a partial buffer copy.

Replay safety
-------------
ReplacingMergeTree on `(match_id, market_type, state_version)` dedups
the same logical row on background merge. The inserter does NOT attempt
exactly-once semantics — at-least-once into ClickHouse is what we want
and what ReplacingMergeTree silently reconciles.

Backpressure
------------
On insert failure the inserter re-queues rows at the *front* of the buffer
and surfaces the exception to the caller. The consumer's retry / DLQ path
then takes over. This means a sustained CH outage will eventually push
messages to the DLQ stream rather than silently growing memory.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from anvil.clickhouse.client import ClickHouseClient

logger = logging.getLogger(__name__)


@dataclass
class TableBuffer:
    """In-memory rows pending insert, keyed by table name."""

    columns: tuple[str, ...]
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)


class BatchInserter:
    """Single-process buffered inserter.

    Designed to be owned by one Anvil worker process. Multi-pod deployments
    have multiple inserters writing concurrently to the same CH cluster;
    that is fine — ClickHouse's MergeTree absorbs concurrent inserts.
    """

    def __init__(
        self,
        client: ClickHouseClient,
        *,
        max_rows: int,
        per_table_cap: int,
        max_age_ms: int,
    ) -> None:
        if max_rows <= 0:
            raise ValueError("max_rows must be positive")
        if per_table_cap <= 0:
            raise ValueError("per_table_cap must be positive")
        if max_age_ms <= 0:
            raise ValueError("max_age_ms must be positive")

        self._client = client
        self._max_rows = max_rows
        self._per_table_cap = per_table_cap
        self._max_age = max_age_ms / 1000.0

        self._buffers: dict[str, TableBuffer] = {}
        self._lock = asyncio.Lock()
        self._last_flush_monotonic = time.monotonic()

        self._flush_count = 0
        self._row_count = 0

    # ---- public surface ---------------------------------------------------

    async def add(self, table: str, columns: tuple[str, ...], row: tuple[Any, ...]) -> None:
        """Append a row. Flushes inline if size triggers fire."""
        async with self._lock:
            buf = self._buffers.get(table)
            if buf is None:
                buf = TableBuffer(columns=columns)
                self._buffers[table] = buf
            elif buf.columns != columns:
                raise RuntimeError(
                    f"column-shape drift for table {table}: stored={buf.columns}, incoming={columns}"
                )
            buf.rows.append(row)

            if len(buf.rows) >= self._per_table_cap or self._total_rows() >= self._max_rows:
                await self._flush_locked(reason="size")

    async def flush(self) -> None:
        """Force a flush of every buffered row. Caller-controlled."""
        async with self._lock:
            await self._flush_locked(reason="explicit")

    async def maybe_flush_age(self) -> None:
        """Flush if the buffer is older than max_age. No-op otherwise."""
        if self._total_rows() == 0:
            self._last_flush_monotonic = time.monotonic()
            return
        if time.monotonic() - self._last_flush_monotonic < self._max_age:
            return
        async with self._lock:
            if time.monotonic() - self._last_flush_monotonic >= self._max_age:
                await self._flush_locked(reason="age")

    async def close(self) -> None:
        """Drain the buffer before shutdown. Best-effort."""
        try:
            await self.flush()
        except Exception:
            logger.exception("batch_close_flush_failed")

    # ---- diagnostics ------------------------------------------------------

    @property
    def buffered_rows(self) -> int:
        return self._total_rows()

    @property
    def flush_count(self) -> int:
        return self._flush_count

    @property
    def row_count(self) -> int:
        return self._row_count

    # ---- internals --------------------------------------------------------

    def _total_rows(self) -> int:
        return sum(len(b) for b in self._buffers.values())

    async def _flush_locked(self, *, reason: str) -> None:
        """Flush every non-empty buffer. Must be called with self._lock held.

        On failure, rows are re-queued at the head of the per-table buffer
        and the exception propagates. The caller (the derived handler) is
        expected to raise, which puts the message back on the consumer's
        retry track.
        """
        non_empty = [(t, b) for t, b in self._buffers.items() if b.rows]
        if not non_empty:
            self._last_flush_monotonic = time.monotonic()
            return

        # Snapshot + clear before insert. On exception we restore.
        snapshot: list[tuple[str, TableBuffer, list[tuple[Any, ...]]]] = []
        for table, buf in non_empty:
            snapshot.append((table, buf, buf.rows))
            buf.rows = []

        try:
            for table, buf, rows in snapshot:
                logger.info(
                    "batch_flush",
                    extra={"table": table, "rows": len(rows), "reason": reason},
                )
                await self._client.insert(table, rows, column_names=buf.columns)
                self._row_count += len(rows)
            self._flush_count += 1
            self._last_flush_monotonic = time.monotonic()
        except Exception:
            # Restore: rows go back to the head of each buffer in original order.
            for table, buf, rows in snapshot:
                buf.rows = rows + buf.rows
            logger.exception(
                "batch_flush_failed_restored_to_buffer",
                extra={
                    "reason": reason,
                    "buffered_rows_total": self._total_rows(),
                },
            )
            raise
