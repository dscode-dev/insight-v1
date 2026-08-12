"""DLQ Replay Service — Sprint 3.6 Part 11.

Admin-only service layer (no UI, no public API) over Atlas's dead
letter stream (insight:stream:dlq, written by the canonical consumer):

  inspect — decode + list entries
  replay  — XADD the original payload back onto its source stream,
            then remove the DLQ entry
  discard — remove the DLQ entry without replaying

This closes the remaining DLQ operational gap: poisoned or
handler-exhausted events are now recoverable without redis-cli surgery.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from prometheus_client import Counter
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

ATLAS_DLQ_REPLAYS_TOTAL = Counter(
    "atlas_dlq_replays_total",
    "DLQ entries replayed back onto their source stream.",
)
ATLAS_DLQ_DISCARDS_TOTAL = Counter(
    "atlas_dlq_discards_total",
    "DLQ entries discarded by an operator.",
)


@dataclass(frozen=True, slots=True)
class DLQEntry:
    entry_id: str
    source_stream: str
    source_entry_id: str
    reason: str
    error: str
    failed_at: str
    payload: str  # the original wire payload, verbatim


class DLQReplayService:
    def __init__(self, redis: Redis, *, dlq_stream: str = "insight:stream:dlq") -> None:
        self._r = redis
        self._dlq = dlq_stream

    async def inspect(self, *, limit: int = 50) -> list[DLQEntry]:
        """Newest-first decoded view of the DLQ."""
        raw = await self._r.xrevrange(self._dlq, count=limit)
        out: list[DLQEntry] = []
        for entry_id, fields in raw:
            body = _field(fields, "payload")
            try:
                decoded = json.loads(body) if body else {}
            except json.JSONDecodeError:
                decoded = {}
            out.append(DLQEntry(
                entry_id=_text(entry_id),
                source_stream=str(decoded.get("source_stream", "")),
                source_entry_id=str(decoded.get("source_entry_id", "")),
                reason=str(decoded.get("reason", "")),
                error=str(decoded.get("error", "")),
                failed_at=str(decoded.get("failed_at", "")),
                payload=str(decoded.get("payload", "")),
            ))
        return out

    async def replay(self, entry_id: str) -> bool:
        """Re-publish one entry's original payload onto its source
        stream, then delete it from the DLQ. Returns False when the
        entry is missing or unreplayable (no source stream/payload)."""
        entry = await self._get(entry_id)
        if entry is None or not entry.source_stream or not entry.payload:
            logger.warning(
                "atlas_dlq_replay_rejected", extra={"entry_id": entry_id}
            )
            return False
        await self._r.xadd(
            entry.source_stream, fields={"payload": entry.payload}
        )
        await self._r.xdel(self._dlq, entry_id)
        ATLAS_DLQ_REPLAYS_TOTAL.inc()
        logger.info(
            "atlas_dlq_replayed",
            extra={"entry_id": entry_id, "source_stream": entry.source_stream},
        )
        return True

    async def discard(self, entry_id: str) -> bool:
        """Remove one entry without replaying."""
        removed = await self._r.xdel(self._dlq, entry_id)
        if removed:
            ATLAS_DLQ_DISCARDS_TOTAL.inc()
            logger.info("atlas_dlq_discarded", extra={"entry_id": entry_id})
        return bool(removed)

    async def _get(self, entry_id: str) -> DLQEntry | None:
        raw = await self._r.xrange(self._dlq, min=entry_id, max=entry_id)
        if not raw:
            return None
        _, fields = raw[0]
        body = _field(fields, "payload")
        try:
            decoded = json.loads(body) if body else {}
        except json.JSONDecodeError:
            decoded = {}
        return DLQEntry(
            entry_id=entry_id,
            source_stream=str(decoded.get("source_stream", "")),
            source_entry_id=str(decoded.get("source_entry_id", "")),
            reason=str(decoded.get("reason", "")),
            error=str(decoded.get("error", "")),
            failed_at=str(decoded.get("failed_at", "")),
            payload=str(decoded.get("payload", "")),
        )


def _field(fields: dict, name: str) -> str:
    for key in (name, name.encode()):
        if key in fields:
            value = fields[key]
            return value.decode() if isinstance(value, bytes) else str(value)
    return ""


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
