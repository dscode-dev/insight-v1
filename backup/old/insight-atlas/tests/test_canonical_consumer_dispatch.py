"""Coverage for the Round-3 fixes to atlas/streaming/canonical_consumer.py:
- _utf8() never raises on invalid UTF-8 bytes.
- ProcessedEventStore.claim()/release() are atomic, not check-then-act.
- _dispatch() is a safety net — an unexpected exception anywhere inside
  _dispatch_body must never propagate and kill the consumer loop.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import fakeredis.aioredis
import pytest

from atlas.streaming.canonical_consumer import (
    CanonicalConsumer,
    ConsumerConfig,
    ProcessedEventStore,
    _utf8,
)


def test_utf8_decodes_valid_bytes():
    assert _utf8(b"hello") == "hello"
    assert _utf8("already-str") == "already-str"


def test_utf8_falls_back_to_hex_on_invalid_bytes():
    invalid = b"\xff\xfe\x00broken"
    result = _utf8(invalid)
    assert result == invalid.hex()  # never raises


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def processed_store(redis_client):
    return ProcessedEventStore(redis_client, key_prefix="test:processed:", ttl_seconds=None)


async def test_claim_wins_once_second_caller_gets_false(processed_store):
    event_id = str(uuid4())
    assert await processed_store.claim(event_id) is True
    # A second, concurrent (or reclaimed) dispatch for the SAME event_id
    # must NOT also win the claim — this is the fix for the check-then-
    # act race the review flagged.
    assert await processed_store.claim(event_id) is False


async def test_release_allows_reclaim(processed_store):
    event_id = str(uuid4())
    assert await processed_store.claim(event_id) is True
    await processed_store.release(event_id)
    # After a failed handler releases the claim, a retry/reclaim must be
    # able to win it again — a stuck permanent claim would silently
    # block every future retry.
    assert await processed_store.claim(event_id) is True


def _wire(event_id: str) -> bytes:
    return json.dumps(
        {
            "schema_version": "v1",
            "stream": "match",
            "idempotency_key": f"{event_id}::confirmed",
            "event": {
                "event_id": event_id,
                "schema_version": "v1",
                "event_type": "match.result",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "match_id": str(uuid4()),
                "competition_id": str(uuid4()),
                "payload": {"home_score": 1, "away_score": 0},
                "source": {"source_id": "api_football"},
                "lineage": [{"source_id": "api_football"}],
                "status": "confirmed",
            },
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
    ).encode("utf-8")


async def test_dispatch_never_propagates_unexpected_exceptions(redis_client, monkeypatch):
    """The core Round-3 fix: before this, an exception anywhere in
    dispatch (e.g. a transient RedisError from the idempotency ledger)
    would propagate out of run()'s loop and permanently kill the
    consumer. _dispatch() must swallow it, log it, and return."""
    consumer = CanonicalConsumer(ConsumerConfig(redis_url="redis://unused"))
    consumer._client = redis_client
    consumer._processed = ProcessedEventStore(
        redis_client, key_prefix="test:processed:", ttl_seconds=None
    )

    async def _boom(_event_id):
        raise RuntimeError("simulated transient Redis failure")

    monkeypatch.setattr(consumer._processed, "claim", _boom)

    async def handler(_envelope):
        pass

    event_id = str(uuid4())
    # Must not raise — that is the entire point of the fix.
    await consumer._dispatch(b"match", b"1-0", {b"payload": _wire(event_id)}, handler)
    assert consumer.consumed_total == 1  # bookkeeping in _dispatch_body still ran
