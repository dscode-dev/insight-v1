"""Publishes captured signals to Atlas via a Redis Stream (ML-D Phase B,
Decisions B-2/B-3).

The `signals/` lake write (explorer/realtime/collector.py) is always
authoritative and happens first; this is a best-effort layer on top. The
envelope wraps a signal in the EXACT `CanonicalSportsEvent` shape Atlas's
canonical consumer already validates
(`atlas/streaming/canonical_consumer.py::_validate_canonical_event` —
required: event_id/schema_version/event_type/occurred_at/competition_id/
payload/source/lineage, `schema_version` must be `"v1"`, `competition_id`
and `event_id` must be UUIDs, `lineage` a non-empty list of dicts) — reusing
existing, already-approved infrastructure instead of inventing a parallel
contract. Atlas does NOT yet have a handler for this stream; wiring that
consumption is explicit work for a later phase of this review (Atlas review)
— this module only needs to be ready to publish spec-compliant envelopes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from explorer.config import EXPLORER_REDIS_URL, EXPLORER_SIGNAL_STREAM_KEY
from explorer.realtime.models import CapturedSignal

SCHEMA_VERSION = "v1"
# Deterministic namespace for the competition_id placeholder — see
# _competition_id_for. Reconciling this against Atlas's real competition
# UUIDs is out of scope here (documented seam for the Atlas review phase).
_COMPETITION_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "insight-explorer/realtime/competition")


class PublisherUnavailable(RuntimeError):
    """Redis is not configured or not reachable."""


def _competition_id_for(signal: CapturedSignal) -> str:
    comp_ref = next((r for r in signal.entity_refs if r.get("type") == "competition"), None)
    seed = (comp_ref or {}).get("external_id") or (comp_ref or {}).get("name") or "unscoped"
    return str(uuid.uuid5(_COMPETITION_NAMESPACE, str(seed)))


def build_envelope(signal: CapturedSignal) -> dict[str, Any]:
    """Pure function: CapturedSignal -> the wire envelope. No I/O — kept
    separate from `SignalPublisher` so the shape can be unit-tested without
    a Redis connection."""
    occurred_at = signal.published_at or signal.captured_at
    event = {
        "event_id": str(uuid.uuid4()),
        "schema_version": SCHEMA_VERSION,
        "event_type": f"signal.{signal.signal_type}",
        "occurred_at": occurred_at,
        "competition_id": _competition_id_for(signal),
        "payload": signal.to_dict(),
        "source": {"source_id": "explorer", "signal_source_id": signal.source_id},
        "lineage": [{"stage": "explorer.realtime.collector", "signal_id": signal.signal_id}],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "stream": "signals",
        "idempotency_key": signal.signal_id,
        "event": event,
        "published_at": signal.captured_at,
    }


class SignalPublisher:
    def __init__(self, redis_url: str | None = None, stream_key: str | None = None,
                 client: Any = None) -> None:
        self.redis_url = EXPLORER_REDIS_URL if redis_url is None else redis_url
        self.stream_key = stream_key or EXPLORER_SIGNAL_STREAM_KEY
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.redis_url:
            raise PublisherUnavailable("EXPLORER_REDIS_URL not configured")
        import redis

        self._client = redis.Redis.from_url(self.redis_url)
        return self._client

    def publish(self, signal: CapturedSignal) -> str:
        """Returns the Redis stream entry id. Raises PublisherUnavailable /
        redis errors on failure — the caller (collector._persist) treats
        that as best-effort and tickets it; the lake write already
        succeeded regardless."""
        envelope = build_envelope(signal)
        client = self._get_client()
        return client.xadd(self.stream_key, {
            "schema_version": SCHEMA_VERSION,
            "event_type": envelope["event"]["event_type"],
            "competition_id": envelope["event"]["competition_id"],
            "payload": json.dumps(envelope, ensure_ascii=False, default=str),
        })
