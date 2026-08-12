"""Derived-stream handler.

The consumer (Anvil's `MultiStreamConsumer`) hands us already-parsed
envelopes with shape:

    {
        "event_id":      "<uuid>",
        "match_id":      "<uuid>",
        "region_code":   "<str>",
        "event_type":    "<MARKET_SNAPSHOT|METRIC_TICK|HUMAN_AGGREGATE_UPDATE>",
        "match_version": <int>,
        "ts_ingest":     "<iso8601>",
        "payload":       { ... }                      # the actual derived payload
    }

For each known event type we map the payload to a column-ordered row and
push it into the BatchInserter. Unknown types are logged + counted, not
errored — analytics should be tolerant of new event types Atlas may
introduce ahead of Anvil knowing about them.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anvil.batch import BatchInserter
from anvil.clickhouse.schemas import (
    MARKET_SNAPSHOTS_COLUMNS,
    MARKET_SNAPSHOTS_TABLE,
    METRIC_TICKS_COLUMNS,
    METRIC_TICKS_TABLE,
)
from anvil.mappers import map_market_snapshot_row, map_metric_tick_row

logger = logging.getLogger(__name__)


@dataclass
class HandlerStats:
    market_snapshots_buffered: int = 0
    metric_ticks_buffered: int = 0
    unsupported: int = 0
    invalid_payload: int = 0


@dataclass
class DerivedEventHandler:
    inserter: BatchInserter
    stats: HandlerStats = field(default_factory=HandlerStats)

    async def handle(
        self,
        event: dict[str, Any],
        ack: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Route one derived event into the batch buffer.

        OWNS the acknowledgement. A buffered row is not durable yet, so
        `ack` is handed to the inserter and only fires once the insert
        carrying that row succeeded. Events that produce no row are
        acknowledged here, immediately — there is nothing to wait for.

        Never acknowledging on an error path is deliberate: the message
        stays pending and Redis redelivers it.
        """
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            self.stats.invalid_payload += 1
            raise ValueError("derived_payload_not_dict")

        if event_type == "MARKET_SNAPSHOT":
            row = map_market_snapshot_row(payload)
            await self.inserter.add(
                MARKET_SNAPSHOTS_TABLE, MARKET_SNAPSHOTS_COLUMNS, row,
                on_flushed=ack,
            )
            self.stats.market_snapshots_buffered += 1
            return

        if event_type == "METRIC_TICK":
            row = map_metric_tick_row(payload)
            await self.inserter.add(
                METRIC_TICKS_TABLE, METRIC_TICKS_COLUMNS, row,
                on_flushed=ack,
            )
            self.stats.metric_ticks_buffered += 1
            return

        # HUMAN_AGGREGATE_UPDATE / HUMAN_SIGNAL / future types: explicit
        # acknowledgement, not error. We do not push these to DLQ — the
        # consumer ACKs them and we move on.
        self.stats.unsupported += 1
        logger.info(
            "derived_event_unsupported_skipped",
            extra={
                "event_type": event_type,
                "match_id": event.get("match_id"),
                "match_version": event.get("match_version"),
            },
        )
        # Nothing was buffered, so nothing will ever flush this message.
        # Without this it would sit pending and be redelivered forever.
        if ack is not None:
            await ack()
