"""Publish validated historical records onto the analytics stream.

    Explorer  →  insight:stream:historical  →  Anvil  →  ClickHouse

WHY THIS EXISTS. The Explorer's lake was the end of the road for historical
data. Atlas reads the `validated/` layer directly for its team-strength
engine, which works, but nothing carried it to the analytical store —
ClickHouse held zero rows while 34,796 validated records sat on disk.

insight-context.md v2.0 assigns "Persistência analítica", "Pipelines para
ClickHouse" and "Dados históricos" to Anvil. The Explorer is not supposed to
know ClickHouse exists, so it publishes and Anvil persists.

WHY A SEPARATE STREAM FROM `insight:stream:derived`. That one carries live
match recalculations from Atlas, and Anvil writes them into tables keyed by
`state_version` with a 90-day TTL. Historical records have no state version
and must never expire. Mixing them would mean one consumer guessing which
shape each entry is, and Nexus — which also watches Atlas's output — would
start seeing five-year-old fixtures as if they had just happened.

BEST-EFFORT BY DESIGN. The lake write is the durable one and happens first.
A publish failure is logged and ticketed; it never fails a collection job.
Redis being down must not cost a season that was already collected — the
backfill command re-publishes from the lake.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

from explorer.observability.logging import get_logger

_log = get_logger("explorer.historical_publisher")

# One stream, not partitioned. The derived stream is sharded across eight
# partitions because live events arrive continuously and ordering per match
# matters; a backfill is a bounded batch nobody is waiting on, and a single
# stream keeps the consumer's ack accounting simple.
HISTORICAL_STREAM_KEY = os.environ.get(
    "EXPLORER_HISTORICAL_STREAM_KEY", "insight:stream:historical"
)

# Entity types Anvil has a historical table for. Anything else is not
# published rather than sent for the consumer to discard: an entry nothing
# can store is backlog that looks like throughput.
PUBLISHABLE = frozenset({"fixture", "stats", "odds_snapshot"})

SCHEMA_VERSION = "explorer.historical.v1"


class HistoricalPublisherUnavailable(RuntimeError):
    """Redis is not configured or not reachable."""


class HistoricalPublisher:
    def __init__(self, redis_url: str | None = None, stream_key: str | None = None,
                 client: Any = None, maxlen: int | None = None) -> None:
        from explorer.config import EXPLORER_REDIS_URL

        self.redis_url = EXPLORER_REDIS_URL if redis_url is None else redis_url
        self.stream_key = stream_key or HISTORICAL_STREAM_KEY
        self._client = client
        # Unbounded by default. Trimming a backfill stream drops the OLDEST
        # entries, which are the ones the consumer has not reached yet — the
        # cap would silently delete exactly the work still owed.
        self.maxlen = maxlen

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.redis_url:
            raise HistoricalPublisherUnavailable("EXPLORER_REDIS_URL not configured")
        import redis

        self._client = redis.Redis.from_url(self.redis_url)
        return self._client

    def publish_many(self, envelopes: Iterable[dict[str, Any]]) -> int:
        """Publish validated envelopes. Returns how many were sent.

        Batched through one pipeline: a season is thousands of records, and a
        round-trip each would make publishing slower than the collection that
        produced them.
        """
        client = self._get_client()
        pipe = client.pipeline(transaction=False)
        queued = 0
        for envelope in envelopes:
            entity_type = envelope.get("entity_type")
            if entity_type not in PUBLISHABLE:
                continue
            pipe.xadd(
                self.stream_key,
                {
                    "schema_version": SCHEMA_VERSION,
                    "entity_type": entity_type,
                    "source": str(envelope.get("source", "")),
                    "competition_key": str(
                        (envelope.get("competition") or {}).get("competition_key", "")),
                    "season": str(envelope.get("season", "")),
                    # The whole envelope: Anvil maps it, and re-deriving
                    # provenance from loose fields would drop the confidence
                    # and trust that let a consumer weigh disagreeing sources.
                    "payload": json.dumps(envelope, ensure_ascii=False, default=str),
                },
                **({"maxlen": self.maxlen, "approximate": True} if self.maxlen else {}),
            )
            queued += 1
        if queued:
            pipe.execute()
        return queued
