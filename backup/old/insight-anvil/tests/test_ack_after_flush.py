"""A stream message is acknowledged only once its row is durable.

The consumer used to ACK as soon as the handler returned. Anvil's handler
only *buffers* the row, so every message between one flush and the next
was marked delivered while its data lived in process memory: a crash or
an ordinary redeploy dropped up to `max_rows` rows permanently, and
nothing reported it — the stream showed them consumed.

These tests pin the replacement contract: `on_flushed` fires after the
insert that carried the row succeeded, and not before.
"""

from __future__ import annotations

from typing import Any

import pytest

from anvil.batch.inserter import BatchInserter
from anvil.handlers.derived_handler import DerivedEventHandler

COLUMNS = ("a", "b")
OTHER_COLUMNS = ("c", "d")


class FakeClient:
    """Records inserts; can be told to fail for specific tables."""

    def __init__(self, fail_tables: set[str] | None = None) -> None:
        self.inserted: list[tuple[str, int]] = []
        self.fail_tables = fail_tables or set()

    async def insert(
        self, table: str, rows: list[tuple[Any, ...]], *, column_names: tuple[str, ...]
    ) -> None:
        if table in self.fail_tables:
            raise RuntimeError(f"clickhouse refused {table}")
        self.inserted.append((table, len(rows)))


def inserter(client: FakeClient, **kwargs) -> BatchInserter:
    params = {"max_rows": 100, "per_table_cap": 100, "max_age_ms": 60_000}
    params.update(kwargs)
    return BatchInserter(client, **params)  # type: ignore[arg-type]


def acker(log: list[str], name: str):
    async def ack() -> None:
        log.append(name)

    return ack


@pytest.mark.asyncio
class TestAckTiming:
    async def test_buffered_row_is_not_acked(self):
        client = FakeClient()
        batch = inserter(client)
        acked: list[str] = []

        await batch.add("t", COLUMNS, (1, 2), on_flushed=acker(acked, "m1"))

        # THE bug this suite exists for: the row is in memory, nothing
        # is durable, so the message must still be pending.
        assert acked == []
        assert client.inserted == []
        assert batch.buffered_rows == 1

    async def test_ack_fires_after_a_successful_flush(self):
        client = FakeClient()
        batch = inserter(client)
        acked: list[str] = []

        await batch.add("t", COLUMNS, (1, 2), on_flushed=acker(acked, "m1"))
        await batch.add("t", COLUMNS, (3, 4), on_flushed=acker(acked, "m2"))
        await batch.flush()

        assert client.inserted == [("t", 2)]
        assert acked == ["m1", "m2"]

    async def test_size_trigger_acks_inline(self):
        client = FakeClient()
        batch = inserter(client, per_table_cap=2)
        acked: list[str] = []

        await batch.add("t", COLUMNS, (1, 2), on_flushed=acker(acked, "m1"))
        assert acked == []
        await batch.add("t", COLUMNS, (3, 4), on_flushed=acker(acked, "m2"))

        # The second add hits the cap and flushes, so both settle.
        assert acked == ["m1", "m2"]

    async def test_rows_without_an_ack_are_fine(self):
        client = FakeClient()
        batch = inserter(client)

        await batch.add("t", COLUMNS, (1, 2))
        await batch.flush()

        assert client.inserted == [("t", 1)]

    async def test_a_failing_ack_does_not_unwind_a_successful_flush(self):
        client = FakeClient()
        batch = inserter(client)
        acked: list[str] = []

        async def boom() -> None:
            raise RuntimeError("redis unreachable")

        await batch.add("t", COLUMNS, (1, 2), on_flushed=boom)
        await batch.add("t", COLUMNS, (3, 4), on_flushed=acker(acked, "m2"))
        await batch.flush()

        # The rows ARE durable. A message left pending is redelivered and
        # re-inserted, which ReplacingMergeTree reconciles; raising here
        # would instead make a succeeded flush look failed.
        assert client.inserted == [("t", 1 + 1)] or client.inserted == [("t", 2)]
        assert acked == ["m2"]


@pytest.mark.asyncio
class TestPartialFlushFailure:
    async def test_successful_table_is_not_reinserted(self):
        # Restoring a table whose insert succeeded re-inserts those rows
        # on the next attempt. ReplacingMergeTree removes the duplicates
        # only on a background merge, and the feature queries use
        # avg()/count()/stddevPop() with no FINAL — so until that merge
        # they read inflated counts and skewed averages.
        client = FakeClient(fail_tables={"bad"})
        batch = inserter(client)

        await batch.add("good", COLUMNS, (1, 2))
        await batch.add("bad", OTHER_COLUMNS, (3, 4))

        with pytest.raises(RuntimeError):
            await batch.flush()

        assert client.inserted == [("good", 1)]
        # Only the failed table is still buffered.
        assert batch.buffered_rows == 1

        client.fail_tables.clear()
        await batch.flush()

        # `good` inserted exactly once across both attempts.
        assert client.inserted == [("good", 1), ("bad", 1)]

    async def test_only_the_durable_rows_are_acked(self):
        client = FakeClient(fail_tables={"bad"})
        batch = inserter(client)
        acked: list[str] = []

        await batch.add("good", COLUMNS, (1, 2), on_flushed=acker(acked, "good-1"))
        await batch.add("bad", OTHER_COLUMNS, (3, 4), on_flushed=acker(acked, "bad-1"))

        with pytest.raises(RuntimeError):
            await batch.flush()

        # The row that landed is acked; the one that did not stays
        # pending so Redis redelivers it.
        assert acked == ["good-1"]

        client.fail_tables.clear()
        await batch.flush()
        assert acked == ["good-1", "bad-1"]

    async def test_restored_rows_keep_their_own_acks(self):
        # rows and acks are parallel lists; a restore that desynchronised
        # them would acknowledge the wrong message.
        client = FakeClient(fail_tables={"t"})
        batch = inserter(client)
        acked: list[str] = []

        for i in range(3):
            await batch.add("t", COLUMNS, (i, i), on_flushed=acker(acked, f"m{i}"))

        with pytest.raises(RuntimeError):
            await batch.flush()
        assert acked == []

        client.fail_tables.clear()
        await batch.flush()
        assert acked == ["m0", "m1", "m2"]


@pytest.mark.asyncio
class TestHandlerOwnsTheAck:
    async def test_a_buffered_event_defers_its_ack(self):
        from tests.wire_payloads import market_snapshot_payload  # type: ignore

        client = FakeClient()
        batch = inserter(client)
        handler = DerivedEventHandler(inserter=batch)
        acked: list[str] = []

        await handler.handle(
            {"event_type": "MARKET_SNAPSHOT", "payload": market_snapshot_payload()},
            acker(acked, "m1"),
        )

        assert acked == []
        await batch.flush()
        assert acked == ["m1"]

    async def test_an_unsupported_event_acks_immediately(self):
        client = FakeClient()
        batch = inserter(client)
        handler = DerivedEventHandler(inserter=batch)
        acked: list[str] = []

        await handler.handle(
            {"event_type": "HUMAN_AGGREGATE_UPDATE", "payload": {}},
            acker(acked, "m1"),
        )

        # Nothing was buffered, so no flush will ever settle it. Without
        # this the message would sit pending and be redelivered forever.
        assert acked == ["m1"]

    async def test_an_invalid_payload_is_never_acked(self):
        client = FakeClient()
        batch = inserter(client)
        handler = DerivedEventHandler(inserter=batch)
        acked: list[str] = []

        with pytest.raises(ValueError):
            await handler.handle(
                {"event_type": "MARKET_SNAPSHOT", "payload": "not-a-dict"},
                acker(acked, "m1"),
            )

        # Leaving it pending sends it down the consumer's retry/DLQ path.
        assert acked == []
