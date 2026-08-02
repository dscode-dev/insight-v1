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
from dataclasses import dataclass
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
    stats: HandlerStats = None  # type: ignore[assignment]  # defaulted below

    def __post_init__(self) -> None:
        if self.stats is None:
            self.stats = HandlerStats()

    async def handle(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            self.stats.invalid_payload += 1
            raise ValueError("derived_payload_not_dict")

        if event_type == "MARKET_SNAPSHOT":
            row = map_market_snapshot_row(payload)
            await self.inserter.add(
                MARKET_SNAPSHOTS_TABLE, MARKET_SNAPSHOTS_COLUMNS, row
            )
            self.stats.market_snapshots_buffered += 1
            return

        if event_type == "METRIC_TICK":
            row = map_metric_tick_row(payload)
            await self.inserter.add(
                METRIC_TICKS_TABLE, METRIC_TICKS_COLUMNS, row
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
