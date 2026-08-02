"""CanonicalEnvelope decode contract — Sprint 5.1.

Unit-level tests for envelope parsing + schema-version enforcement.
Full XREADGROUP / XACK behaviour is exercised in the E2E harness
(insight-sports-hub/e2e/run_v1.sh), not here — keeping these tests
hermetic so the suite stays fast.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.streaming.canonical_consumer import (
    CanonicalEnvelope,
    MalformedEnvelopeError,
    UnsupportedSchemaError,
)


def _wire(version: str = "v1", event_type: str = "match.result") -> bytes:
    """Build a minimal wire envelope matching the Hub's v1 shape."""
    return json.dumps(
        {
            "schema_version": version,
            "stream": "match",
            "idempotency_key": "e1::confirmed",
            "event": {
                "event_id": "e6858cb3-8b6d-4eab-8c75-0545cf52c974",
                "schema_version": version,
                "event_type": event_type,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "match_id": str(uuid4()),
                "competition_id": str(uuid4()),
                "payload": {"home_score": 1, "away_score": 0},
                "source": {
                    "source_id": "api_football",
                    "source_name": "API Football",
                    "source_type": "commercial_api",
                    "confidence": 0.95,
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
                "lineage": [
                    {
                        "source_id": "api_football",
                        "source_name": "API Football",
                        "source_type": "commercial_api",
                        "confidence": 0.95,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
                "status": "confirmed",
            },
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
    ).encode("utf-8")


def test_envelope_decodes_v1_happy_path() -> None:
    env = CanonicalEnvelope.from_payload(_wire())
    assert env.schema_version == "v1"
    assert env.stream == "match"
    assert env.idempotency_key == "e1::confirmed"
    assert env.event["event_type"] == "match.result"


def test_envelope_rejects_unsupported_schema() -> None:
    with pytest.raises(UnsupportedSchemaError):
        CanonicalEnvelope.from_payload(_wire(version="v99"))


def test_envelope_rejects_missing_schema_version() -> None:
    body = json.dumps({"event": {"event_type": "match.fixture"}}).encode("utf-8")
    with pytest.raises(UnsupportedSchemaError):
        CanonicalEnvelope.from_payload(body)


def test_envelope_rejects_missing_event() -> None:
    body = json.dumps(
        {"schema_version": "v1", "stream": "match"}
    ).encode("utf-8")
    with pytest.raises(MalformedEnvelopeError):
        CanonicalEnvelope.from_payload(body)


def test_envelope_decodes_z_terminated_timestamp() -> None:
    body = json.dumps(
        {
            "schema_version": "v1",
            "stream": "context",
            "idempotency_key": "e2::candidate",
            "event": {
                "event_id": "e6858cb3-8b6d-4eab-8c75-0545cf52c974",
                "schema_version": "v1",
                "event_type": "competition.standings",
                "occurred_at": "2026-06-01T12:00:00Z",
                "competition_id": str(uuid4()),
                "payload": {"table": []},
                "source": {"source_id": "api_football"},
                "lineage": [{"source_id": "api_football"}],
            },
            "published_at": "2026-06-01T12:00:00Z",
        }
    ).encode("utf-8")
    env = CanonicalEnvelope.from_payload(body)
    assert env.published_at == datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_envelope_rejects_missing_required_event_field() -> None:
    body = json.loads(_wire().decode("utf-8"))
    del body["event"]["lineage"]
    with pytest.raises(MalformedEnvelopeError):
        CanonicalEnvelope.from_payload(json.dumps(body).encode("utf-8"))


def test_envelope_requires_match_id_for_match_events() -> None:
    body = json.loads(_wire().decode("utf-8"))
    del body["event"]["match_id"]
    with pytest.raises(MalformedEnvelopeError):
        CanonicalEnvelope.from_payload(json.dumps(body).encode("utf-8"))
