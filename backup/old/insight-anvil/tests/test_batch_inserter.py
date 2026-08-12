"""BatchInserter coverage.

Critical behaviours:
  * Flushes when per-table cap is reached.
  * Flushes when cumulative max_rows is reached.
  * Flushes on explicit `.flush()` call.
  * `maybe_flush_age()` flushes once max_age has elapsed.
  * On insert failure, rows are re-queued at the head of their buffer
    and the exception propagates (so the consumer retries the message).
  * Column-shape drift across two adds to the same table raises loudly.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable

import pytest

from anvil.batch import BatchInserter


class FakeClient:
    """Records every insert. Optional `fail_n` makes the first N calls raise."""

    def __init__(self, *, fail_n: int = 0) -> None:
        self.calls: list[tuple[str, list[tuple], list[str]]] = []
        self._fail_n = fail_n

    async def insert(
        self,
        table: str,
        data: list[tuple[Any, ...]],
        *,
        column_names: Iterable[str],
    ) -> None:
        if self._fail_n > 0:
            self._fail_n -= 1
            raise RuntimeError("simulated CH outage")
        self.calls.append((table, list(data), list(column_names)))

    async def command(self, sql: str) -> Any:  # pragma: no cover (not used here)
        return None

    async def ping(self) -> bool:  # pragma: no cover (not used here)
        return True

    async def close(self) -> None:  # pragma: no cover
        return None


COLS = ("a", "b")


def _new_inserter(client: FakeClient, **overrides) -> BatchInserter:
    return BatchInserter(
        client=client,
        max_rows=overrides.get("max_rows", 100),
        per_table_cap=overrides.get("per_table_cap", 50),
        max_age_ms=overrides.get("max_age_ms", 500),
    )


def _run(coro):
    return asyncio.run(coro)


def test_flush_on_per_table_cap():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c, per_table_cap=3)
        await ins.add("t1", COLS, (1, "a"))
        await ins.add("t1", COLS, (2, "b"))
        assert ins.buffered_rows == 2
        assert c.calls == []
        await ins.add("t1", COLS, (3, "c"))
        # per_table_cap hit → flush
        assert len(c.calls) == 1
        assert c.calls[0][0] == "t1"
        assert len(c.calls[0][1]) == 3
        assert ins.buffered_rows == 0

    _run(go())


def test_flush_on_total_max_rows_across_tables():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c, per_table_cap=100, max_rows=3)
        await ins.add("t1", COLS, (1, "a"))
        await ins.add("t2", COLS, (2, "b"))
        assert c.calls == []
        await ins.add("t1", COLS, (3, "c"))
        # max_rows hit (3 total) → flush both buffers
        assert len(c.calls) == 2
        names = {call[0] for call in c.calls}
        assert names == {"t1", "t2"}
        assert ins.buffered_rows == 0

    _run(go())


def test_explicit_flush_drains_buffer():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c, per_table_cap=100, max_rows=100)
        await ins.add("t1", COLS, (1, "a"))
        await ins.add("t1", COLS, (2, "b"))
        await ins.flush()
        assert len(c.calls) == 1
        assert len(c.calls[0][1]) == 2
        assert ins.flush_count == 1

    _run(go())


def test_close_drains_remaining_rows():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c, per_table_cap=100, max_rows=100)
        await ins.add("t1", COLS, (1, "a"))
        await ins.close()
        assert len(c.calls) == 1

    _run(go())


def test_maybe_flush_age_fires_after_max_age():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c, per_table_cap=100, max_rows=100, max_age_ms=20)
        await ins.add("t1", COLS, (1, "a"))
        # Not yet older than 20ms.
        await ins.maybe_flush_age()
        assert c.calls == []
        # Wait + tick: now age-flush should fire.
        await asyncio.sleep(0.03)
        await ins.maybe_flush_age()
        assert len(c.calls) == 1

    _run(go())


def test_insert_failure_restores_rows_to_buffer_and_raises():
    async def go():
        c = FakeClient(fail_n=1)
        ins = _new_inserter(c, per_table_cap=2, max_rows=2)
        await ins.add("t1", COLS, (1, "a"))
        with pytest.raises(RuntimeError, match="simulated CH outage"):
            await ins.add("t1", COLS, (2, "b"))
        # Rows must be restored — consumer's retry path expects to re-handle.
        assert ins.buffered_rows == 2
        # Next add succeeds and now has 3 buffered rows (cap=2, so triggers).
        await ins.add("t1", COLS, (3, "c"))
        # The second flush (cap-triggered) sent all 3 rows in original order.
        assert len(c.calls) == 1
        assert [r[0] for r in c.calls[0][1]] == [1, 2, 3]

    _run(go())


def test_column_shape_drift_raises():
    async def go():
        c = FakeClient()
        ins = _new_inserter(c)
        await ins.add("t1", ("a", "b"), (1, "x"))
        with pytest.raises(RuntimeError, match="column-shape drift"):
            await ins.add("t1", ("a", "b", "c"), (1, "x", 9))

    _run(go())
