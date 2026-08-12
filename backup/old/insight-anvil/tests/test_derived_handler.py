"""Derived event handler dispatch coverage.

  * MARKET_SNAPSHOT events land in the market_snapshots buffer.
  * METRIC_TICK events land in the metric_ticks buffer.
  * Unknown event types are counted as skipped, NOT raised — they reach
    the consumer's ACK path normally so the stream advances.
  * Invalid payloads (missing `payload` dict) raise so the consumer's
    retry / DLQ path takes over.
"""

from __future__ import annotations

import asyncio
from typing import Any, Iterable
from uuid import uuid4

import pytest

from anvil.batch import BatchInserter
from anvil.clickhouse.schemas import MARKET_SNAPSHOTS_TABLE, METRIC_TICKS_TABLE
from anvil.handlers import DerivedEventHandler

from .wire_payloads import market_snapshot_payload, metric_tick_payload


class RecordingClient:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, list, list[str]]] = []

    async def insert(
        self,
        table: str,
        data: list,
        *,
        column_names: Iterable[str],
    ) -> None:
        self.inserts.append((table, list(data), list(column_names)))

    async def command(self, sql: str) -> Any:  # pragma: no cover
        return None

    async def ping(self) -> bool:  # pragma: no cover
        return True

    async def close(self) -> None:  # pragma: no cover
        return None


def _market_snapshot_event() -> dict:
    payload = market_snapshot_payload()
    return {
        "event_type": "MARKET_SNAPSHOT",
        "match_id": payload["match_id"],
        "match_version": 1,
        "payload": payload,
    }


def _metric_tick_event() -> dict:
    payload = metric_tick_payload()
    return {
        "event_type": "METRIC_TICK",
        "match_id": payload["match_id"],
        "match_version": 1,
        "payload": payload,
    }


def _new_handler() -> tuple[DerivedEventHandler, RecordingClient]:
    client = RecordingClient()
    inserter = BatchInserter(
        client=client, max_rows=1, per_table_cap=1, max_age_ms=1000
    )
    return DerivedEventHandler(inserter=inserter), client


def _run(coro):
    return asyncio.run(coro)


def test_market_snapshot_event_routes_to_market_snapshots_table():
    async def go():
        handler, client = _new_handler()
        await handler.handle(_market_snapshot_event())
        # per_table_cap=1 means the single row flushes immediately.
        assert len(client.inserts) == 1
        assert client.inserts[0][0] == MARKET_SNAPSHOTS_TABLE
        assert handler.stats.market_snapshots_buffered == 1

    _run(go())


def test_metric_tick_event_routes_to_metric_ticks_table():
    async def go():
        handler, client = _new_handler()
        await handler.handle(_metric_tick_event())
        assert len(client.inserts) == 1
        assert client.inserts[0][0] == METRIC_TICKS_TABLE
        assert handler.stats.metric_ticks_buffered == 1

    _run(go())


def test_unsupported_event_type_is_skipped_not_raised():
    async def go():
        handler, client = _new_handler()
        # The consumer normally ACKs after handler returns; we must NOT
        # raise on unknown event types or the stream will get stuck.
        await handler.handle(
            {
                "event_type": "HUMAN_AGGREGATE_UPDATE",
                "match_id": str(uuid4()),
                "payload": {"some": "future-shape"},
            }
        )
        assert client.inserts == []
        assert handler.stats.unsupported == 1

    _run(go())


def test_invalid_payload_raises_for_retry_path():
    async def go():
        handler, _ = _new_handler()
        with pytest.raises(ValueError, match="derived_payload_not_dict"):
            await handler.handle(
                {
                    "event_type": "MARKET_SNAPSHOT",
                    "payload": "not-a-dict",
                }
            )
        assert handler.stats.invalid_payload == 1

    _run(go())
