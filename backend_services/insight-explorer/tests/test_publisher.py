"""Publisher tests. The envelope-shape checks mirror Atlas's
`_validate_canonical_event` rules (atlas/streaming/canonical_consumer.py) —
Explorer can't import Atlas's validator directly (separate Poetry projects),
so this is a documented contract-drift guard, not a cross-service import.
"""

import json
from datetime import datetime
from uuid import UUID

import fakeredis
import pytest

from explorer.realtime.models import CapturedSignal
from explorer.realtime.publisher import PublisherUnavailable, SignalPublisher, build_envelope


def _assert_matches_atlas_canonical_event_contract(envelope: dict) -> None:
    assert envelope["schema_version"] == "v1"
    event = envelope["event"]
    for field in ("event_id", "schema_version", "event_type", "occurred_at",
                 "competition_id", "payload", "source", "lineage"):
        assert field in event, f"missing required field: {field}"
    assert event["schema_version"] == "v1"
    UUID(event["event_id"])  # raises if not a UUID
    UUID(event["competition_id"])
    assert isinstance(event["event_type"], str) and event["event_type"]
    assert not event["event_type"].startswith("match.")  # would additionally require match_id
    occurred_at = datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
    assert occurred_at.tzinfo is not None
    assert isinstance(event["payload"], dict)
    assert isinstance(event["source"], dict)
    assert isinstance(event["lineage"], list) and event["lineage"]
    assert all(isinstance(item, dict) for item in event["lineage"])


def _signal(**overrides) -> CapturedSignal:
    base = dict(signal_type="injury", source_id="src-1", text="Player X doubtful",
               captured_at="2026-08-04T12:00:00Z", published_at="2026-08-04T11:55:00Z")
    base.update(overrides)
    return CapturedSignal(**base)


def test_build_envelope_matches_atlas_canonical_event_contract():
    _assert_matches_atlas_canonical_event_contract(build_envelope(_signal()))


def test_build_envelope_derives_stable_competition_id_from_entity_ref():
    signal = _signal(entity_refs=[{"type": "competition", "external_id": "brasileirao_serie_a"}])
    e1 = build_envelope(signal)["event"]["competition_id"]
    e2 = build_envelope(signal)["event"]["competition_id"]
    assert e1 == e2  # deterministic — same seed, same uuid5 every time
    UUID(e1)


def test_build_envelope_falls_back_to_unscoped_when_no_competition_ref():
    envelope = build_envelope(_signal(entity_refs=[]))
    UUID(envelope["event"]["competition_id"])  # still a valid UUID, never crashes


def test_build_envelope_idempotency_key_is_the_signal_id():
    signal = _signal()
    envelope = build_envelope(signal)
    assert envelope["idempotency_key"] == signal.signal_id


def test_publisher_raises_when_redis_not_configured():
    publisher = SignalPublisher(redis_url="")
    with pytest.raises(PublisherUnavailable):
        publisher.publish(_signal())


def test_publisher_xadds_the_envelope_via_fakeredis():
    client = fakeredis.FakeRedis()
    publisher = SignalPublisher(stream_key="insight:stream:events:signals", client=client)
    signal = _signal()
    publisher.publish(signal)

    entries = client.xrange("insight:stream:events:signals")
    assert len(entries) == 1
    _, fields = entries[0]
    payload = json.loads(fields[b"payload"])
    _assert_matches_atlas_canonical_event_contract(payload)
    assert fields[b"event_type"] == b"signal.injury"


def test_publisher_reuses_injected_client_across_calls():
    client = fakeredis.FakeRedis()
    publisher = SignalPublisher(stream_key="s", client=client)
    publisher.publish(_signal())
    publisher.publish(_signal())
    assert len(client.xrange("s")) == 2
