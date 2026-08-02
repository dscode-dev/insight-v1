"""Trend stream publisher.

Publishes structured trend events onto a dedicated Redis Stream
(`insight:stream:trends` by default) — the contract Nexus and any other
downstream consumer will read. Same envelope discipline as the
canonical streams: a JSON body under a single `payload` field plus
top-level routing hints, MAXLEN-bounded.

Atlas's responsibility ends at this stream. No posts, no users, no UI.
"""

from __future__ import annotations

import logging

import orjson
from prometheus_client import Counter
from redis.asyncio import Redis

from atlas.trends.models import TREND_SCHEMA_VERSION, Trend

logger = logging.getLogger(__name__)

TRENDS_PUBLISHED_TOTAL = Counter(
    "trends_published_total",
    "Trends published onto the trend stream.",
    ["trend_type", "category"],
)
TRENDS_PUBLISH_FAILED_TOTAL = Counter(
    "trends_publish_failed_total",
    "Trend publish attempts that failed at the Redis boundary.",
)


class TrendPublisher:
    def __init__(
        self,
        redis: Redis,
        *,
        stream: str = "insight:stream:trends",
        maxlen: int = 100_000,
    ) -> None:
        self._r = redis
        self._stream = stream
        self._maxlen = maxlen

    @property
    def stream(self) -> str:
        return self._stream

    async def publish(self, trend: Trend, *, priority: bool = False) -> str | None:
        """XADD one trend. Returns the entry id, or None on failure
        (logged + counted — the caller already persisted the trend, so a
        publish failure is recoverable by replay, not fatal).

        `priority` (Sprint 1.5) marks PRIORITY_PUBLISH trends with a
        top-level flag so consumers can fast-path them without parsing
        the JSON payload."""
        body = {
            "schema_version": TREND_SCHEMA_VERSION,
            "priority": priority,
            "trend": trend.to_wire(),
        }
        try:
            entry_id = await self._r.xadd(
                self._stream,
                {
                    "schema_version": TREND_SCHEMA_VERSION,
                    "trend_type": trend.trend_type.value,
                    "category": trend.category.value,
                    "agent": trend.agent or "",
                    "severity": trend.severity.value if trend.severity else "",
                    "priority": "true" if priority else "false",
                    "canonical_match_id": str(trend.canonical_match_id),
                    "payload": orjson.dumps(body),
                },
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception:  # noqa: BLE001 — transport failure must not break ingestion
            TRENDS_PUBLISH_FAILED_TOTAL.inc()
            logger.exception(
                "trend_publish_failed",
                extra={
                    "trend_id": str(trend.trend_id),
                    "trend_type": trend.trend_type.value,
                    "stream": self._stream,
                },
            )
            return None
        TRENDS_PUBLISHED_TOTAL.labels(
            trend_type=trend.trend_type.value, category=trend.category.value
        ).inc()
        logger.info(
            "trend_published",
            extra={
                "trend_id": str(trend.trend_id),
                "trend_type": trend.trend_type.value,
                "category": trend.category.value,
                "canonical_match_id": str(trend.canonical_match_id),
                "strength": trend.strength,
                "confidence": trend.confidence,
                "entry_id": entry_id.decode() if isinstance(entry_id, bytes) else entry_id,
            },
        )
        return entry_id.decode() if isinstance(entry_id, bytes) else entry_id

    async def publish_many(self, trends: list[Trend], *, priority: bool = False) -> int:
        published = 0
        for trend in trends:
            if await self.publish(trend, priority=priority) is not None:
                published += 1
        return published
