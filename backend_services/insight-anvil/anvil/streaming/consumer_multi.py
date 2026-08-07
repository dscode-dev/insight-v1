from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from anvil.runtime.consumer_metrics import (
    event_end_to_end_lag_seconds,
    events_dlq_total,
    events_failed_total,
    events_processed_total,
    handler_duration_seconds,
)
from anvil.runtime.tracing import span
from anvil.streaming.dlq import DlqWriter
from anvil.streaming.jsonx import loads

logger = logging.getLogger(__name__)


# Upper bound on `match_version` envelope field length. The field is parsed
# with `int()`, which has no built-in size limit; a hostile producer can
# submit a multi-megabyte digit string and DoS the worker via CPU spent in
# the parser. 18 chars is comfortably above any plausible monotonic counter
# we'd ever encounter (10^18 events per match would take ~31 trillion years
# at 1 event/ms).
_MATCH_VERSION_MAX_LEN = 18


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int
    backoff_seconds: list[int]
    retry_hash_prefix: str
    retry_ttl_seconds: int


class RetryTracker:
    def __init__(self, redis_client: Redis, policy: RetryPolicy):
        self._r = redis_client
        self._p = policy

    def _key(self, stream: str, group: str, msg_id: str) -> str:
        return f"{self._p.retry_hash_prefix}:{stream}:{group}:{msg_id}"

    async def can_attempt_now(self, stream: str, group: str, msg_id: str, now_ts: int) -> bool:
        k = self._key(stream, group, msg_id)
        raw = await self._r.hget(k, b"next_ts")
        if not raw:
            return True
        next_ts = int(raw)
        return now_ts >= next_ts

    async def register_failure(self, stream: str, group: str, msg_id: str, now_ts: int) -> dict:
        k = self._key(stream, group, msg_id)

        pipe = self._r.pipeline()
        pipe.hincrby(k, b"attempts", 1)
        pipe.hsetnx(k, b"first_ts", now_ts)
        pipe.expire(k, self._p.retry_ttl_seconds)
        res = await pipe.execute()

        attempts = int(res[0])

        backoff_idx = min(attempts - 1, len(self._p.backoff_seconds) - 1)
        next_ts = now_ts + int(self._p.backoff_seconds[backoff_idx])

        await self._r.hset(k, mapping={b"next_ts": next_ts, b"last_ts": now_ts})
        await self._r.expire(k, self._p.retry_ttl_seconds)

        return {"attempts": attempts, "next_ts": next_ts}

    async def clear(self, stream: str, group: str, msg_id: str) -> None:
        await self._r.delete(self._key(stream, group, msg_id))


class MultiStreamConsumer:
    """
    Consumer produção:
    - multi streams partitions
    - fairness loop: pending + new
    - XAUTOCLAIM
    - retry/backoff + DLQ
    - ACK somente após handler sucesso (handler garante side-effects)
    - graceful shutdown via stop()

    The loop respects an internal stop signal so a SIGTERM/SIGINT handler can
    drain cleanly. After stop() is signalled the consumer finishes the
    in-flight message, exits the inner loops, and returns from start(). It
    does not abandon a message mid-handler; the caller's deploy budget should
    allow for one handler-duration's worth of post-SIGTERM work.
    """

    # Maximum DLQ push attempts before we give up and ACK without DLQ.
    # If the DLQ itself is failing, blocking forever just guarantees the
    # message can never advance and the PEL grows without bound.
    _DLQ_MAX_ATTEMPTS = 3

    def __init__(
        self,
        redis_client: Redis,
        *,
        stream_keys: list[str],
        group_name: str,
        consumer_name: str,
        dlq_key: str,
        retry_policy: RetryPolicy,
        block_ms: int,
        read_count: int,
        claim_idle_ms: int,
        claim_count: int,
        pending_quota: int,
        new_quota: int,
        max_payload_bytes: int,
        parser: Callable[[dict], dict] | None = None,
    ):
        """`parser` turns raw Redis fields into the event the handler gets.

        Defaults to the DERIVED-stream envelope (event_id, match_id,
        region_code, event_type, match_version, ts_ingest, payload). That
        shape was the only one this consumer had ever carried, so it was
        hardcoded — and reusing the consumer for the historical stream failed
        every message with `missing_required_field field=event_id`, because a
        five-year-old fixture has no match version and no region.

        Making it injectable, rather than adding optional fields to the
        derived parser, keeps the live path strict: a derived event that
        genuinely lost its event_id must still fail loudly.
        """
        if not stream_keys:
            raise ValueError("stream_keys must not be empty")
        if max_payload_bytes <= 0:
            raise ValueError("max_payload_bytes must be positive")

        self._r = redis_client
        self._streams = stream_keys
        self._group = group_name
        self._consumer = consumer_name
        self._parser = parser

        self._block_ms = block_ms
        self._read_count = read_count
        self._claim_idle_ms = claim_idle_ms
        self._claim_count = claim_count
        self._pending_quota = pending_quota
        self._new_quota = new_quota
        self._max_payload_bytes = max_payload_bytes

        self._retry = RetryTracker(redis_client, retry_policy)
        self._dlq = DlqWriter(redis_client=redis_client, dlq_key=dlq_key)

        self._stop_event = asyncio.Event()

    async def ensure_groups(self) -> None:
        """Create the consumer group on every stream, idempotently.

        The previous implementation caught any Exception here and logged the
        "group already exists" message, which masked real connectivity errors
        at startup. We now discriminate by the `BUSYGROUP` Redis error code
        — only that one means "already exists"; everything else is fatal.
        """
        for s in self._streams:
            try:
                await self._r.xgroup_create(
                    name=s, groupname=self._group, id="$", mkstream=True
                )
                logger.info(
                    "consumer_group_created",
                    extra={"stream": s, "group": self._group},
                )
            except ResponseError as exc:
                # Redis convention: pre-existing consumer-group errors begin
                # with the literal token `BUSYGROUP`. Anything else (auth
                # failure, NOPERM, OOM) must surface to the caller.
                if "BUSYGROUP" in str(exc):
                    logger.info(
                        "consumer_group_exists",
                        extra={"stream": s, "group": self._group},
                    )
                    continue
                logger.exception(
                    "consumer_group_create_failed",
                    extra={"stream": s, "group": self._group, "error": str(exc)},
                )
                raise

    def stop(self) -> None:
        """Request a graceful shutdown.

        Idempotent; safe to call from a signal handler. The running loop
        finishes the in-flight message and then exits start().
        """
        self._stop_event.set()

    @property
    def stopping(self) -> bool:
        return self._stop_event.is_set()

    async def start(self, handler: Callable[[dict], Awaitable[None]]) -> None:
        await self.ensure_groups()

        logger.info(
            "consumer_start",
            extra={"streams": self._streams, "group": self._group, "consumer": self._consumer},
        )

        rr = 0
        while not self._stop_event.is_set():
            processed_pending = await self._process_pending(
                handler, quota=self._pending_quota, start_index=rr
            )
            rr = (rr + 1) % len(self._streams)

            if self._stop_event.is_set():
                break

            processed_new = await self._process_new(handler, quota=self._new_quota)

            if processed_pending == 0 and processed_new == 0:
                # Tiny sleep when both paths are idle, interruptible by stop().
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=0.01)
                except asyncio.TimeoutError:
                    pass

        logger.info(
            "consumer_stopped",
            extra={"streams": self._streams, "group": self._group, "consumer": self._consumer},
        )

    async def _process_pending(self, handler, *, quota: int, start_index: int) -> int:
        remaining = quota
        if remaining <= 0:
            return 0

        processed = 0
        n = len(self._streams)

        for i in range(n):
            if remaining <= 0 or self._stop_event.is_set():
                break

            stream = self._streams[(start_index + i) % n]

            # XAUTOCLAIM: pega mensagens órfãs
            try:
                resp = await self._r.xautoclaim(
                    name=stream,
                    groupname=self._group,
                    consumername=self._consumer,
                    min_idle_time=self._claim_idle_ms,
                    start_id="0-0",
                    count=min(self._claim_count, remaining),
                )
                claimed = resp[1] if resp else []
            except Exception:
                logger.exception(
                    "pel_reclaim_failed",
                    extra={"stream": stream, "group": self._group, "consumer": self._consumer},
                )
                claimed = []

            for msg_id, fields in claimed:
                if remaining <= 0 or self._stop_event.is_set():
                    break
                await self._process_one(handler, stream, msg_id, fields, source="pending")
                processed += 1
                remaining -= 1

        return processed

    async def _process_new(self, handler, *, quota: int) -> int:
        remaining = quota
        if remaining <= 0:
            return 0

        resp = await self._r.xreadgroup(
            groupname=self._group,
            consumername=self._consumer,
            streams={s: ">" for s in self._streams},
            count=min(self._read_count, remaining),
            block=self._block_ms,
        )
        if not resp:
            return 0

        processed = 0
        for stream_name, entries in resp:
            stream = stream_name.decode() if isinstance(stream_name, (bytes, bytearray)) else str(stream_name)
            for msg_id, fields in entries:
                if remaining <= 0 or self._stop_event.is_set():
                    break
                await self._process_one(handler, stream, msg_id, fields, source="new")
                processed += 1
                remaining -= 1
            if remaining <= 0 or self._stop_event.is_set():
                break

        return processed

    async def _process_one(self, handler, stream: str, msg_id, raw_fields: dict, source: str) -> None:
        msg_id_str = msg_id.decode() if isinstance(msg_id, (bytes, bytearray)) else str(msg_id)
        now_ts = int(time.time())

        if not await self._retry.can_attempt_now(stream, self._group, msg_id_str, now_ts):
            return

        handler_t0 = time.perf_counter()
        # One root span per message. Handler and downstream calls become
        # child spans implicitly via OTel's context-var propagation, which
        # crosses await boundaries on the same task.
        with span(
            "consumer.process_message",
            attributes={
                "messaging.system": "redis-streams",
                "messaging.destination.name": stream,
                "messaging.consumer.group": self._group,
                "messaging.consumer.id": self._consumer,
                "messaging.message.id": msg_id_str,
                "messaging.source.kind": source,
            },
        ):
            await self._process_one_inner(
                handler, stream, msg_id, msg_id_str, raw_fields, source, handler_t0, now_ts
            )

    async def _process_one_inner(
        self,
        handler,
        stream: str,
        msg_id,
        msg_id_str: str,
        raw_fields: dict,
        source: str,
        handler_t0: float,
        now_ts: int,
    ) -> None:
        try:
            event = self._parse(raw_fields)

            # The handler OWNS the acknowledgement.
            #
            # Anvil's handler only buffers the row; it becomes durable on
            # a later batch flush. ACKing here — as this consumer used to
            # — marked messages delivered while their rows were still in
            # memory, so a crash or a redeploy dropped them silently.
            # Passing the ack through lets the handler fire it after the
            # flush that carried the row.
            #
            # An un-acked message stays pending and Redis redelivers it
            # via XAUTOCLAIM: at-least-once, which ReplacingMergeTree
            # reconciles. Failing to ack is therefore the safe direction.
            acked = False

            async def ack() -> None:
                nonlocal acked
                if acked:
                    return
                acked = True
                await self._r.xack(stream, self._group, msg_id)
                await self._retry.clear(stream, self._group, msg_id_str)

            await handler(event, ack)

            handler_elapsed = time.perf_counter() - handler_t0
            event_type = event.get("event_type") or "unknown"
            handler_duration_seconds.labels(stream=stream, event_type=event_type).observe(
                handler_elapsed
            )

            # End-to-end lag: best-effort using ts_ingest. Missing/invalid
            # timestamps fall back to 0 rather than poisoning the histogram.
            ts_ingest_str = event.get("ts_ingest") or ""
            try:
                ts_ingest_epoch = time.mktime(
                    time.strptime(ts_ingest_str[:19], "%Y-%m-%dT%H:%M:%S")
                )
                lag = max(0.0, time.time() - ts_ingest_epoch)
                event_end_to_end_lag_seconds.labels(
                    stream=stream, event_type=event_type
                ).observe(lag)
            except Exception:
                pass

            events_processed_total.labels(
                stream=stream, group=self._group, event_type=event_type, source=source
            ).inc()

            logger.info(
                "event_handled",
                extra={
                    # False means the row is buffered and the ack fires
                    # on the next flush — not a failure.
                    "acked_inline": acked,
                    "source": source,
                    "stream": stream,
                    "group": self._group,
                    "consumer": self._consumer,
                    "message_id": msg_id_str,
                    "event_type": event.get("event_type"),
                    "match_id": event.get("match_id"),
                    "match_version": event.get("match_version"),
                },
            )

        except Exception as exc:
            info = await self._retry.register_failure(stream, self._group, msg_id_str, now_ts)
            attempts = int(info["attempts"])

            events_failed_total.labels(
                stream=stream,
                group=self._group,
                event_type=(raw_fields.get(b"event_type") or b"unknown").decode(errors="replace")
                if isinstance(raw_fields.get(b"event_type"), (bytes, bytearray))
                else "unknown",
                source=source,
            ).inc()

            if attempts >= self._retry._p.max_retries:
                # Try to push to DLQ. Bounded retry: if DLQ is unreachable for
                # _DLQ_MAX_ATTEMPTS in a row, ACK the message anyway with a
                # very loud error log. The alternative (looping forever on the
                # DLQ failure) wedges the consumer and lets the PEL grow.
                dlq_ok = False
                last_dlq_error: Exception | None = None
                for dlq_attempt in range(1, self._DLQ_MAX_ATTEMPTS + 1):
                    try:
                        await self._dlq.push(
                            source_stream=stream,
                            group=self._group,
                            message_id=msg_id_str,
                            raw_fields=raw_fields,
                            error=str(exc),
                            attempts=attempts,
                            source=source,
                        )
                        dlq_ok = True
                        break
                    except Exception as dlq_exc:
                        last_dlq_error = dlq_exc
                        logger.exception(
                            "dlq_push_failed_will_retry",
                            extra={
                                "stream": stream,
                                "group": self._group,
                                "message_id": msg_id_str,
                                "dlq_attempt": dlq_attempt,
                            },
                        )

                # Always ACK after max retries, even if DLQ failed. The retry
                # hash still records the failure for postmortem.
                await self._r.xack(stream, self._group, msg_id)
                await self._retry.clear(stream, self._group, msg_id_str)

                events_dlq_total.labels(
                    stream=stream,
                    group=self._group,
                    outcome="ok" if dlq_ok else "dlq_unreachable",
                ).inc()

                if dlq_ok:
                    logger.exception(
                        "event_failed_dlq_acked",
                        extra={
                            "stream": stream,
                            "group": self._group,
                            "message_id": msg_id_str,
                            "attempts": attempts,
                        },
                    )
                else:
                    logger.critical(
                        "event_failed_dlq_unreachable_acked",
                        extra={
                            "stream": stream,
                            "group": self._group,
                            "message_id": msg_id_str,
                            "attempts": attempts,
                            "dlq_error": str(last_dlq_error) if last_dlq_error else None,
                        },
                    )
            else:
                logger.exception(
                    "event_failed_will_retry",
                    extra={"stream": stream, "group": self._group, "message_id": msg_id_str, "attempts": attempts},
                )

    def _parse(self, raw_fields: dict) -> dict:
        if self._parser is not None:
            return self._parser(raw_fields)
        payload_raw = self._required_bytes(raw_fields, b"payload")
        payload_size = len(payload_raw)
        if payload_size > self._max_payload_bytes:
            raise ValueError(
                f"payload_too_large bytes={payload_size} max={self._max_payload_bytes}"
            )

        payload = loads(payload_raw)
        return {
            "event_id": self._decode_envelope_field(raw_fields, b"event_id", max_len=64),
            "match_id": self._decode_envelope_field(raw_fields, b"match_id", max_len=64),
            "region_code": self._decode_envelope_field(raw_fields, b"region_code", max_len=32),
            "event_type": self._decode_envelope_field(raw_fields, b"event_type", max_len=64),
            "match_version": self._parse_match_version(raw_fields),
            "ts_ingest": self._decode_envelope_field(raw_fields, b"ts_ingest", max_len=64),
            "payload": payload,
        }

    @staticmethod
    def _required_bytes(raw_fields: dict, key: bytes) -> bytes:
        value = raw_fields.get(key)
        if value is None:
            raise ValueError(f"missing_required_field field={key.decode(errors='replace')}")
        if not isinstance(value, (bytes, bytearray)):
            raise ValueError(f"invalid_field_type field={key.decode(errors='replace')}")
        return bytes(value)

    @staticmethod
    def _optional_bytes(raw_fields: dict, key: bytes, default: bytes) -> bytes:
        value = raw_fields.get(key, default)
        if not isinstance(value, (bytes, bytearray)):
            raise ValueError(f"invalid_field_type field={key.decode(errors='replace')}")
        return bytes(value)

    def _decode_envelope_field(self, raw_fields: dict, key: bytes, *, max_len: int) -> str:
        value = self._required_bytes(raw_fields, key)
        if len(value) > max_len:
            raise ValueError(
                f"envelope_field_too_large field={key.decode(errors='replace')} "
                f"bytes={len(value)} max={max_len}"
            )
        return value.decode("utf-8")

    @staticmethod
    def _parse_match_version(raw_fields: dict) -> int:
        """Bound the raw bytes before calling `int()` to neutralise the
        unbounded-int parser DoS vector. See `_MATCH_VERSION_MAX_LEN`.
        """
        value = raw_fields.get(b"match_version", b"0")
        if not isinstance(value, (bytes, bytearray)):
            raise ValueError("invalid_field_type field=match_version")
        if len(value) > _MATCH_VERSION_MAX_LEN:
            raise ValueError(
                f"match_version_field_too_large bytes={len(value)} max={_MATCH_VERSION_MAX_LEN}"
            )
        try:
            parsed = int(bytes(value).decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            raise ValueError("invalid_match_version_not_int")
        if parsed < 0:
            raise ValueError("invalid_match_version_negative")
        return parsed
