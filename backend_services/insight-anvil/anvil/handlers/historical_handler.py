"""Historical-stream handler.

    Explorer  →  insight:stream:historical  →  THIS  →  ClickHouse

The Explorer publishes validated `explorer.envelope.v1` records; this routes
each one into the historical table for its `entity_type`.

WHY IT IS NOT THE DERIVED HANDLER. That one consumes Atlas's live match
recalculations and writes tables keyed by `state_version` with a 90-day TTL.
These records have no state version and must never expire — insight-context.md
v2.0 puts "Dados históricos" under Anvil, and a five-year backfill in a table
that forgets after ninety days is not history.

ACKNOWLEDGEMENT IS THE SAME CONTRACT as the derived handler, and for the same
reason: a buffered row is not durable, so `ack` travels with the row and fires
after the insert that carried it. An envelope that produces no row is
acknowledged here — otherwise it sits pending and is redelivered forever.

A MALFORMED ENVELOPE IS ACKNOWLEDGED, NOT RETRIED. It cannot become valid on
redelivery: the same bytes map the same way every time. Leaving it pending
would block nothing (the consumer moves on) but would grow a pending list
nobody can drain, and the count would read as backlog.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from anvil.batch import BatchInserter
from anvil.clickhouse.schemas import (
    HISTORICAL_FIXTURES_COLUMNS,
    HISTORICAL_FIXTURES_TABLE,
    HISTORICAL_ODDS_COLUMNS,
    HISTORICAL_ODDS_TABLE,
    HISTORICAL_STATS_COLUMNS,
    HISTORICAL_STATS_TABLE,
)
from anvil.mappers.historical import (
    HistoricalMappingError,
    map_fixture_row,
    map_odds_row,
    map_stats_row,
)

logger = logging.getLogger(__name__)

_ROUTES: dict[str, tuple[str, tuple[str, ...], Any]] = {
    "fixture": (HISTORICAL_FIXTURES_TABLE, HISTORICAL_FIXTURES_COLUMNS, map_fixture_row),
    "odds_snapshot": (HISTORICAL_ODDS_TABLE, HISTORICAL_ODDS_COLUMNS, map_odds_row),
    "stats": (HISTORICAL_STATS_TABLE, HISTORICAL_STATS_COLUMNS, map_stats_row),
}


@dataclass
class HistoricalStats:
    fixtures_buffered: int = 0
    odds_buffered: int = 0
    stats_buffered: int = 0
    unsupported: int = 0
    malformed: int = 0


@dataclass
class HistoricalEventHandler:
    inserter: BatchInserter
    stats: HistoricalStats = field(default_factory=HistoricalStats)

    async def handle(
        self,
        event: dict[str, Any],
        ack: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        envelope = event.get("payload") if isinstance(event.get("payload"), dict) else event
        entity_type = envelope.get("entity_type") or event.get("entity_type")

        route = _ROUTES.get(str(entity_type))
        if route is None:
            self.stats.unsupported += 1
            logger.info(
                "historical_entity_unsupported_skipped",
                extra={"entity_type": entity_type,
                       "source": envelope.get("source")},
            )
            if ack is not None:
                await ack()
            return

        table, columns, mapper = route
        try:
            row = mapper(envelope)
        except HistoricalMappingError as exc:
            # Deterministic: the same bytes map the same way on every
            # redelivery. Acknowledge and record, rather than accumulate a
            # pending list that reads as backlog and can never drain.
            self.stats.malformed += 1
            logger.warning(
                "historical_envelope_malformed",
                extra={"entity_type": entity_type,
                       "source": envelope.get("source"),
                       "external_id": envelope.get("external_id"),
                       "error": str(exc)},
            )
            if ack is not None:
                await ack()
            return

        await self.inserter.add(table, columns, row, on_flushed=ack)
        if entity_type == "fixture":
            self.stats.fixtures_buffered += 1
        elif entity_type == "odds_snapshot":
            self.stats.odds_buffered += 1
        else:
            self.stats.stats_buffered += 1


def parse_historical_fields(raw_fields: dict) -> dict:
    """Redis stream fields → the event `HistoricalEventHandler.handle` reads.

    The consumer's default parser expects the DERIVED envelope — event_id,
    match_id, region_code, match_version, ts_ingest. A historical record has
    none of those: it is a fixture from 2020, not the Nth recalculation of a
    live match. Reusing that parser rejected all 34,801 backfilled entries
    with `missing_required_field field=event_id`.

    What this needs is only the payload; everything else on the wire is there
    so an operator can read the stream with XRANGE and see what an entry is
    without decoding JSON.
    """
    payload_raw = raw_fields.get(b"payload")
    if not payload_raw:
        raise ValueError("missing_required_field field=payload")

    from anvil.streaming.jsonx import loads

    envelope = loads(payload_raw)
    if not isinstance(envelope, dict):
        raise ValueError("historical_payload_not_object")

    def _text(key: bytes) -> str:
        value = raw_fields.get(key)
        return value.decode("utf-8", errors="replace") if value else ""

    return {
        "entity_type": _text(b"entity_type") or envelope.get("entity_type"),
        "source": _text(b"source"),
        "competition_key": _text(b"competition_key"),
        "season": _text(b"season"),
        "payload": envelope,
    }
