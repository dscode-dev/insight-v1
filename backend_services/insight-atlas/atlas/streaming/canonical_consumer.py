"""Atlas canonical-event consumer — Sprint 5.1.

Atlas reads CanonicalSportsEvent envelopes the Sports Data Hub
publishes onto two Redis Streams:

  - insight:stream:events:match    — match.fixture, match.result
  - insight:stream:events:context  — competition.standings, everything else

The wire envelope (defined in
`insight-sports-hub/internal/adapters/publishing/redis_publisher.go`)
is JSON-encoded under the stream entry's "payload" field:

  {
    "schema_version": "v1",
    "stream": "match" | "odds" | "context",
    "idempotency_key": "<canonical_event_id>::<status>",
    "event": { ...CanonicalSportsEvent... },
    "published_at": "<RFC3339 UTC>"
  }

# Architectural rules
- Atlas NEVER calls provider APIs.
- Atlas NEVER consumes provider payloads directly.
- Atlas only reads canonicalized events from this consumer.
- Schema version is enforced; unknown versions are routed to a side
  channel (log + counter) rather than silently consumed.

# Delivery semantics
- Redis Consumer Groups give at-least-once delivery + per-consumer
  pending lists. The handler MUST be idempotent over
  `envelope.idempotency_key` — Sprint 5.1 keeps idempotency in the
  feature store (writing the same FeatureSnapshot under the same id
  is a no-op).
- XACK on successful handle. On failure: leave pending so a future
  XCLAIM (insight-sports-hub Sprint 5.1 Part 6) can reclaim it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as redis_asyncio
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)


# --- Wire-version handling --------------------------------------------------

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"v1"})


class UnsupportedSchemaError(ValueError):
    """Raised when an envelope's schema_version is unknown.

    The consumer treats this as a poison message: the entry is ACK'd
    (so it does not redeliver forever) but routed to a counter + log
    line so operators can see a producer drift.
    """


class MalformedEnvelopeError(ValueError):
    """Raised when an envelope or canonical event violates the v1 contract."""


EVENTS_RECEIVED_TOTAL = Counter(
    "events_received_total",
    "Canonical Redis stream events received by Atlas.",
)
EVENTS_PROCESSED_TOTAL = Counter(
    "events_processed_total",
    "Canonical Redis stream events processed by Atlas.",
)
EVENTS_FAILED_TOTAL = Counter(
    "events_failed_total",
    "Canonical Redis stream events Atlas failed to process.",
    ["reason"],
)
EVENTS_DUPLICATE_TOTAL = Counter(
    "events_duplicate_total",
    "Canonical Redis stream events skipped because their event_id was already processed.",
)
EVENTS_DLQ_TOTAL = Counter(
    "events_dlq_total",
    "Canonical Redis stream events sent to the Atlas DLQ.",
    ["reason"],
)
PROCESSING_LATENCY_SECONDS = Histogram(
    "processing_latency_seconds",
    "Seconds spent processing one canonical Redis stream event.",
)


# --- DTOs -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CanonicalEnvelope:
    """Decoded envelope as Atlas sees it.

    `event` is left as the raw mapping because Atlas's FeatureSnapshot
    pipeline maps a slightly different shape (UUID match_id, etc.) and
    keeping the dict here avoids over-modelling at the boundary.
    """

    schema_version: str
    stream: str
    idempotency_key: str
    event: dict[str, Any]
    published_at: datetime

    @classmethod
    def from_payload(cls, raw: bytes | str) -> CanonicalEnvelope:
        """Decode and validate the JSON payload field."""
        if raw in (b"", ""):
            raise MalformedEnvelopeError("payload field is missing or empty")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise MalformedEnvelopeError("envelope payload is not a JSON object")
        version = body.get("schema_version")
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            raise UnsupportedSchemaError(
                f"unsupported schema_version: {version!r}"
            )
        event = body.get("event")
        if not isinstance(event, dict):
            raise MalformedEnvelopeError("envelope.event missing or not an object")
        _validate_canonical_event(event, envelope_schema_version=str(version))
        # Tolerate either bare ISO strings or full RFC3339 with offset.
        published_at_raw = body.get("published_at", "")
        try:
            published_at = datetime.fromisoformat(
                published_at_raw.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            raise MalformedEnvelopeError("published_at is missing or invalid") from None
        idempotency_key = body.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise MalformedEnvelopeError("idempotency_key missing or invalid")
        return cls(
            schema_version=str(version),
            stream=str(body.get("stream", "")),
            idempotency_key=idempotency_key,
            event=event,
            published_at=published_at,
        )


# --- Config ----------------------------------------------------------------


@dataclass(slots=True)
class ConsumerConfig:
    """Composition-root inputs.

    `streams` is the list the consumer XREADGROUPs from. Sprint 5.1
    ships two: match + context. Adding odds is a config change, no
    code change.
    """

    redis_url: str
    group: str = "insight-atlas"
    consumer_name: str = "atlas-1"
    streams: tuple[str, ...] = (
        "insight:stream:events:match",
        "insight:stream:events:context",
    )
    block_ms: int = 5_000
    batch_count: int = 32
    payload_field: str = "payload"
    dlq_stream: str = "insight:stream:dlq"
    processed_key_prefix: str = "atlas:processed_events:"
    processed_ttl_seconds: int | None = None
    retry_key_prefix: str = "atlas:canonical_retry:"
    pending_reclaim_idle_ms: int = 60_000
    pending_reclaim_count: int = 32
    max_handler_attempts: int = 5


# Handler signature — what the application layer plugs in.
EnvelopeHandler = Callable[[CanonicalEnvelope], Awaitable[None]]


class ProcessedEventStore:
    """Redis-backed idempotency ledger keyed by canonical event_id.

    `claim()`/`release()` replace the earlier `seen()`-then-later-
    `mark_processed()` pair, which was check-then-act: under multiple
    consumer replicas (or the same event delivered twice via
    `_reclaim_pending`'s XCLAIM racing the main XREADGROUP loop), two
    dispatches could both observe `seen() == False` before either
    marked the key, and both would run the handler — silent duplicate
    processing. `claim()` is atomic (`SET NX`); only the dispatch that
    wins the claim proceeds.
    """

    def __init__(
        self,
        client: redis_asyncio.Redis,
        *,
        key_prefix: str,
        ttl_seconds: int | None = None,
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self._ttl = ttl_seconds

    def _key(self, event_id: str) -> str:
        return f"{self._prefix}{event_id}"

    async def claim(self, event_id: str) -> bool:
        """Atomically claim `event_id` for processing. True = this call
        won the claim (proceed with the handler); False = another
        dispatch already holds it (treat as a duplicate delivery)."""
        key = self._key(event_id)
        if self._ttl is None:
            claimed = await self._client.set(key, "processed", nx=True)
        else:
            claimed = await self._client.set(key, "processed", nx=True, ex=self._ttl)
        return bool(claimed)

    async def release(self, event_id: str) -> None:
        """Undo a claim after a failed handler, so a retry (attempt
        counter still below the limit) or a later XCLAIM reclaim can
        legitimately re-claim and re-process this event_id."""
        await self._client.delete(self._key(event_id))


# --- Consumer --------------------------------------------------------------


class CanonicalConsumer:
    """Long-lived Redis Streams consumer feeding the feature pipeline.

    Lifetime: `run(handler)` blocks until cancellation. Construct + run
    inside an asyncio task supervised by the FastAPI lifespan.

    The consumer is INTENTIONALLY decoupled from the FeaturePipeline —
    it hands every decoded envelope to the supplied handler. The
    composition root wires a handler that calls `build_snapshot()` +
    `FeatureStore.put()`. Keeping the seam this thin makes unit tests
    + replay tools trivial.
    """

    def __init__(self, cfg: ConsumerConfig) -> None:
        self.cfg = cfg
        self._client: redis_asyncio.Redis | None = None
        self._stop = asyncio.Event()
        # Counters surfaced via /metrics + /ready.
        self.consumed_total: int = 0
        self.acked_total: int = 0
        self.rejected_unsupported: int = 0
        self.failed_decode: int = 0
        self.failed_handler: int = 0
        self.duplicate_total: int = 0
        self.dlq_total: int = 0
        self.last_event_at: datetime | None = None

    # -- lifecycle ----------------------------------------------------------

    async def connect(self) -> None:
        """Open the Redis connection + ensure consumer groups exist.

        Idempotent on the group create (XGROUP CREATE returns BUSYGROUP
        when re-running, which we tolerate).
        """
        self._client = redis_asyncio.from_url(self.cfg.redis_url, decode_responses=False)
        await self._client.ping()
        for stream in self.cfg.streams:
            await self._ensure_group(stream)
        self._processed = ProcessedEventStore(
            self._client,
            key_prefix=self.cfg.processed_key_prefix,
            ttl_seconds=self.cfg.processed_ttl_seconds,
        )
        logger.info(
            "atlas_canonical_consumer_connected",
            extra={"streams": list(self.cfg.streams), "group": self.cfg.group},
        )

    async def _ensure_group(self, stream: str) -> None:
        assert self._client is not None
        try:
            await self._client.xgroup_create(
                name=stream, groupname=self.cfg.group, id="$", mkstream=True
            )
        except redis_asyncio.ResponseError as exc:
            msg = str(exc)
            # Already exists — fine.
            if "BUSYGROUP" not in msg:
                raise

    async def close(self) -> None:
        self._stop.set()
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("atlas_canonical_consumer_closed")

    async def reconnect(self) -> None:
        """Drop and re-open the Redis connection WITHOUT setting `_stop`
        — unlike `close()` (final shutdown), this is for a supervisor
        that wants `run()` to be callable again afterwards. Used when
        `run()` exits unexpectedly (a bug, a fatal connection error) and
        the caller wants to restart it (see `app.py`'s consumer
        supervisor loop)."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                logger.warning("atlas_consumer_reconnect_close_failed", exc_info=True)
            self._client = None
        await self.connect()

    # -- main loop ----------------------------------------------------------

    async def run(self, handler: EnvelopeHandler) -> None:
        """Block consuming + dispatching envelopes to `handler`.

        Handler exceptions below the configured attempt limit are not
        ACKed; the entry stays in the pending list and this consumer
        reclaims it after the idle timeout. At the attempt limit the
        entry is routed to DLQ and ACKed.
        """
        if self._client is None:
            await self.connect()
        assert self._client is not None
        streams_arg: dict[bytes | str, str] = {s: ">" for s in self.cfg.streams}
        while not self._stop.is_set():
            try:
                await self._reclaim_pending(handler)
                resp = await self._client.xreadgroup(
                    groupname=self.cfg.group,
                    consumername=self.cfg.consumer_name,
                    streams=streams_arg,
                    count=self.cfg.batch_count,
                    block=self.cfg.block_ms,
                )
            except asyncio.CancelledError:
                break
            except redis_asyncio.RedisError as exc:
                logger.warning("atlas_consumer_read_error: %s", exc)
                # Back off briefly so a hammering reconnect loop
                # doesn't saturate the box.
                await asyncio.sleep(1.0)
                continue
            if not resp:
                continue
            for stream_key, entries in resp:
                for entry_id, fields in entries:
                    await self._dispatch(stream_key, entry_id, fields, handler)

    async def _reclaim_pending(self, handler: EnvelopeHandler) -> None:
        assert self._client is not None
        for stream in self.cfg.streams:
            claimed = await self._client.xautoclaim(
                name=stream,
                groupname=self.cfg.group,
                consumername=self.cfg.consumer_name,
                min_idle_time=self.cfg.pending_reclaim_idle_ms,
                start_id="0-0",
                count=self.cfg.pending_reclaim_count,
            )
            entries = claimed[1] if len(claimed) > 1 else []
            for entry_id, fields in entries:
                await self._dispatch(stream, entry_id, fields, handler)

    async def _dispatch(
        self,
        stream_key: bytes | str,
        entry_id: bytes | str,
        fields: dict[bytes, bytes],
        handler: EnvelopeHandler,
    ) -> None:
        """Safety net around `_dispatch_body`.

        Before this existed, any exception `_dispatch_body` didn't
        already handle via one of its specific `except` clauses
        (typically a transient RedisError from `xack`/`xadd`/the
        idempotency ledger, or a bad-encoding payload — see `_utf8`)
        propagated all the way out of `run()`'s loop with no supervisor
        to restart it: one bad event permanently killed ingestion for
        the whole process, silently (health checks weren't wired to
        this either — see the app.py health-check fix). Anything caught
        here is logged + counted and the entry is deliberately left
        un-ACKed (not assumed to be a poison message) so XCLAIM retries
        it once whatever broke recovers.
        """
        stream = _utf8(stream_key)
        eid = _utf8(entry_id)
        try:
            await self._dispatch_body(stream, eid, fields, handler)
        except Exception as exc:
            EVENTS_FAILED_TOTAL.labels(reason="dispatch_crash").inc()
            logger.exception(
                "atlas_dispatch_crashed",
                extra={"stream": stream, "entry_id": eid, "err": str(exc)},
            )

    async def _dispatch_body(
        self,
        stream: str,
        eid: str,
        fields: dict[bytes, bytes],
        handler: EnvelopeHandler,
    ) -> None:
        assert self._client is not None
        self.consumed_total += 1
        EVENTS_RECEIVED_TOTAL.inc()
        payload = fields.get(self.cfg.payload_field.encode(), b"")
        started = time.perf_counter()
        try:
            envelope = CanonicalEnvelope.from_payload(payload)
        except UnsupportedSchemaError as exc:
            self.rejected_unsupported += 1
            EVENTS_FAILED_TOTAL.labels(reason="unsupported_schema").inc()
            logger.warning(
                "atlas_envelope_unsupported_schema",
                extra={"stream": stream, "entry_id": eid, "err": str(exc)},
            )
            await self._send_to_dlq(
                stream=stream,
                entry_id=eid,
                reason="unsupported_schema",
                err=str(exc),
                payload=payload,
            )
            await self._client.xack(stream, self.cfg.group, eid)
            return
        except (MalformedEnvelopeError, ValueError, json.JSONDecodeError) as exc:
            self.failed_decode += 1
            EVENTS_FAILED_TOTAL.labels(reason="malformed").inc()
            logger.warning(
                "atlas_envelope_decode_failed",
                extra={"stream": stream, "entry_id": eid, "err": str(exc)},
            )
            await self._send_to_dlq(
                stream=stream,
                entry_id=eid,
                reason="malformed",
                err=str(exc),
                payload=payload,
            )
            await self._client.xack(stream, self.cfg.group, eid)
            return

        assert hasattr(self, "_processed")
        event_id = str(envelope.event["event_id"])
        # Atomic claim (SET NX), not check-then-act: two dispatches
        # racing the same event_id (multi-replica consumers, or XCLAIM
        # reclaiming an entry the original consumer is still slowly
        # working) must not both proceed past this point.
        if not await self._processed.claim(event_id):
            self.duplicate_total += 1
            EVENTS_DUPLICATE_TOTAL.inc()
            await self._client.xack(stream, self.cfg.group, eid)
            logger.info(
                "atlas_envelope_duplicate_skipped",
                extra={
                    "stream": stream,
                    "entry_id": eid,
                    "event_id": event_id,
                    "idempotency_key": envelope.idempotency_key,
                },
            )
            return

        try:
            await handler(envelope)
        except Exception as exc:
            self.failed_handler += 1
            EVENTS_FAILED_TOTAL.labels(reason="handler").inc()
            # Undo the claim — a failed attempt must not permanently
            # block a later retry/reclaim from re-processing this event.
            await self._processed.release(event_id)
            attempts = await self._record_handler_failure(event_id)
            logger.warning(
                "atlas_envelope_handler_failed",
                extra={
                    "stream": stream,
                    "entry_id": eid,
                    "event_id": event_id,
                    "idempotency_key": envelope.idempotency_key,
                    "attempts": attempts,
                    "max_attempts": self.cfg.max_handler_attempts,
                    "err": str(exc),
                },
                exc_info=True,
            )
            if attempts >= self.cfg.max_handler_attempts:
                await self._send_to_dlq(
                    stream=stream,
                    entry_id=eid,
                    reason="handler_failed",
                    err=str(exc),
                    payload=payload,
                )
                await self._client.xack(stream, self.cfg.group, eid)
            # Below the attempt limit there is no XACK: the message
            # remains pending for bounded retry/reclaim.
            return

        await self._clear_handler_failures(event_id)
        await self._client.xack(stream, self.cfg.group, eid)
        self.acked_total += 1
        EVENTS_PROCESSED_TOTAL.inc()
        PROCESSING_LATENCY_SECONDS.observe(time.perf_counter() - started)
        self.last_event_at = datetime.now(timezone.utc)
        logger.info(
            "atlas_envelope_handled",
            extra={
                "stream": stream,
                "entry_id": eid,
                "schema_version": envelope.schema_version,
                "idempotency_key": envelope.idempotency_key,
                "event_id": event_id,
            },
        )

    async def _send_to_dlq(
        self,
        *,
        stream: str,
        entry_id: str,
        reason: str,
        err: str,
        payload: bytes | str,
    ) -> None:
        assert self._client is not None
        body = {
            "source_stream": stream,
            "source_entry_id": entry_id,
            "consumer_group": self.cfg.group,
            "consumer_name": self.cfg.consumer_name,
            "reason": reason,
            "error": err,
            "payload": _utf8(payload),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._client.xadd(
            self.cfg.dlq_stream,
            fields={"payload": json.dumps(body, separators=(",", ":"))},
        )
        self.dlq_total += 1
        EVENTS_DLQ_TOTAL.labels(reason=reason).inc()
        logger.warning(
            "atlas_envelope_sent_to_dlq",
            extra={
                "stream": stream,
                "entry_id": entry_id,
                "dlq_stream": self.cfg.dlq_stream,
                "reason": reason,
            },
        )

    async def _record_handler_failure(self, event_id: str) -> int:
        assert self._client is not None
        key = f"{self.cfg.retry_key_prefix}{event_id}"
        attempts = await self._client.incr(key)
        if self.cfg.processed_ttl_seconds is not None:
            await self._client.expire(key, self.cfg.processed_ttl_seconds)
        return int(attempts)

    async def _clear_handler_failures(self, event_id: str) -> None:
        assert self._client is not None
        await self._client.delete(f"{self.cfg.retry_key_prefix}{event_id}")

    # -- introspection -----------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Read-only counters for /metrics + /ready."""
        return {
            "streams": list(self.cfg.streams),
            "group": self.cfg.group,
            "consumer_name": self.cfg.consumer_name,
            "consumed_total": self.consumed_total,
            "acked_total": self.acked_total,
            "rejected_unsupported": self.rejected_unsupported,
            "failed_decode": self.failed_decode,
            "failed_handler": self.failed_handler,
            "duplicate_total": self.duplicate_total,
            "dlq_total": self.dlq_total,
            "last_event_at": (
                self.last_event_at.isoformat()
                if self.last_event_at is not None
                else None
            ),
        }


def _utf8(value: bytes | str) -> str:
    """Never raises: a non-UTF-8 payload must still be logged/DLQ'd, not
    crash the very error path meant to record it (mirrors
    `atlas/runtime/logging.py::_safe`'s bytes handling)."""
    if not isinstance(value, bytes):
        return value
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.hex()


def _validate_canonical_event(
    event: dict[str, Any], *, envelope_schema_version: str
) -> None:
    required = (
        "event_id",
        "schema_version",
        "event_type",
        "occurred_at",
        "competition_id",
        "payload",
        "source",
        "lineage",
    )
    missing = [name for name in required if name not in event]
    if missing:
        raise MalformedEnvelopeError(
            f"canonical event missing required fields: {','.join(missing)}"
        )
    if event["schema_version"] != envelope_schema_version:
        raise MalformedEnvelopeError("event schema_version does not match envelope")
    _require_uuid(event["event_id"], "event_id")
    _require_uuid(event["competition_id"], "competition_id")
    event_type = event["event_type"]
    if not isinstance(event_type, str) or not event_type:
        raise MalformedEnvelopeError("event_type missing or invalid")
    if event_type.startswith("match."):
        if "match_id" not in event:
            raise MalformedEnvelopeError("match_id required for match events")
        _require_uuid(event["match_id"], "match_id")
    if "match_id" in event and event["match_id"] not in (None, ""):
        _require_uuid(event["match_id"], "match_id")
    try:
        occurred_at = datetime.fromisoformat(
            str(event["occurred_at"]).replace("Z", "+00:00")
        )
    except ValueError:
        raise MalformedEnvelopeError("occurred_at missing or invalid") from None
    if occurred_at.tzinfo is None:
        raise MalformedEnvelopeError("occurred_at must include timezone")
    if not isinstance(event["payload"], dict):
        raise MalformedEnvelopeError("payload missing or invalid")
    # match.odds is its own canonical category. It rides the generic
    # match.* contract above (match_id is required + UUID-checked) and
    # additionally carries a normalized odds payload. Validate the
    # minimum shape the odds pipeline relies on, preserving every
    # existing rule for other event types.
    if event_type == "match.odds":
        payload = event["payload"]
        for field_name in ("market", "bookmaker"):
            value = payload.get(field_name)
            if not isinstance(value, str) or not value:
                raise MalformedEnvelopeError(
                    f"odds payload missing required field: {field_name}"
                )
    if not isinstance(event["source"], dict):
        raise MalformedEnvelopeError("source missing or invalid")
    lineage = event["lineage"]
    if not isinstance(lineage, list) or not lineage:
        raise MalformedEnvelopeError("lineage missing or empty")
    if not all(isinstance(item, dict) for item in lineage):
        raise MalformedEnvelopeError("lineage entries must be objects")


def _require_uuid(value: Any, field_name: str) -> None:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        raise MalformedEnvelopeError(f"{field_name} missing or invalid") from None
