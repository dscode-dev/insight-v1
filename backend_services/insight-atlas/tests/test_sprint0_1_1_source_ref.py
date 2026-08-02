"""Coverage for Sprint 0.1.1 — SourceRef hardening.

Two design axes the tests must lock down:

  * Additive-only contract — payloads that only carried the V1 trio
    (source_id + source_type + confidence) still deserialise cleanly.
    Sprint 0.1.1 tests in this file MUST NOT break the older tests in
    test_sprint0_1_guards.py (covered by running the full suite).

  * New fields behave per spec — source_name fallback, observed_at
    tz-awareness + default, adapter_version + metadata serialisation
    round-trip, full lineage payload reconstructs identically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atlas.contracts import SourceRef, SourceType


# ---------------------------------------------------------------------------
# Additive-only check (the most important promise)
# ---------------------------------------------------------------------------


def test_v1_short_form_still_validates() -> None:
    """The Sprint 0.1 minimal SourceRef (id + type + confidence) must
    keep working without ANY change at the call site — this is the
    'do not break existing serialization' guarantee."""
    ref = SourceRef(
        source_id="api_football",
        source_type=SourceType.commercial_api,
        confidence=0.95,
    )
    # Backward-compat defaults applied transparently.
    assert ref.source_id == "api_football"
    assert ref.source_name == "api_football"  # filled from source_id
    assert ref.observed_at is not None
    assert ref.observed_at.tzinfo is not None
    assert ref.adapter_version is None
    assert ref.metadata == {}


def test_v1_serialised_payload_round_trips() -> None:
    """A persisted Sprint 0.1 payload (only the 3 V1 fields on the
    wire) must deserialise under Sprint 0.1.1 without error."""
    legacy_payload = {
        "source_id": "sportmonks",
        "source_type": "commercial_api",
        "confidence": 0.88,
    }
    ref = SourceRef.model_validate(legacy_payload)
    assert ref.source_name == "sportmonks"
    assert ref.adapter_version is None


# ---------------------------------------------------------------------------
# New fields — explicit values
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_full_lineage_payload_round_trips() -> None:
    """The shape future Sports Data Hub will emit: every field set."""
    observed = _now() - timedelta(seconds=12)
    ref = SourceRef(
        source_id="api_football",
        source_name="API-Football v3",
        source_type=SourceType.commercial_api,
        confidence=0.95,
        observed_at=observed,
        adapter_version="api_football@1.4.2",
        metadata={
            "endpoint": "/v3/fixtures/12345",
            "etag": 'W/"abc-123"',
            "rate_limit_remaining": 42,
        },
    )
    dumped = ref.model_dump(mode="json")
    restored = SourceRef.model_validate(dumped)
    assert restored.source_name == "API-Football v3"
    assert restored.adapter_version == "api_football@1.4.2"
    assert restored.metadata["endpoint"] == "/v3/fixtures/12345"
    assert restored.metadata["rate_limit_remaining"] == 42
    # Timestamp survives the JSON round-trip including tz.
    assert restored.observed_at == observed


def test_source_name_explicitly_set_is_preserved() -> None:
    """When the producer DOES send source_name, the after-validator
    must NOT overwrite it with source_id."""
    ref = SourceRef(
        source_id="api_football",
        source_name="API-Football (Spain feed)",
        source_type=SourceType.commercial_api,
        confidence=0.7,
    )
    assert ref.source_name == "API-Football (Spain feed)"


# ---------------------------------------------------------------------------
# observed_at — tz awareness
# ---------------------------------------------------------------------------


def test_observed_at_rejects_naive_datetime() -> None:
    naive = datetime(2026, 5, 10, 14, 30)  # no tz
    with pytest.raises(ValueError, match="timezone-aware"):
        SourceRef(
            source_id="api_football",
            source_type=SourceType.commercial_api,
            confidence=0.9,
            observed_at=naive,
        )


def test_observed_at_default_is_now_utc() -> None:
    """Default fallback for old payloads — fills with a tz-aware
    'now' so the wire stays consistent."""
    before = datetime.now(timezone.utc)
    ref = SourceRef(
        source_id="api_football",
        source_type=SourceType.commercial_api,
        confidence=0.9,
    )
    after = datetime.now(timezone.utc)
    assert before <= ref.observed_at <= after
    assert ref.observed_at.tzinfo is not None


# ---------------------------------------------------------------------------
# adapter_version + metadata
# ---------------------------------------------------------------------------


def test_adapter_version_optional_max_length() -> None:
    too_long = "x" * 65
    with pytest.raises(ValueError):
        SourceRef(
            source_id="api_football",
            source_type=SourceType.commercial_api,
            confidence=0.9,
            adapter_version=too_long,
        )


def test_metadata_accepts_nested_structures() -> None:
    """Metadata is `dict[str, Any]` — nested lists/dicts/primitives
    must survive serialisation."""
    ref = SourceRef(
        source_id="api_football",
        source_type=SourceType.commercial_api,
        confidence=0.9,
        metadata={
            "nested": {"k": [1, 2, 3]},
            "headers": ["application/json", "gzip"],
            "ints": 42,
            "floats": 3.14,
            "bool": True,
        },
    )
    restored = SourceRef.model_validate(ref.model_dump(mode="json"))
    assert restored.metadata["nested"]["k"] == [1, 2, 3]
    assert restored.metadata["headers"] == ["application/json", "gzip"]
    assert restored.metadata["bool"] is True


def test_metadata_default_is_empty_dict_per_instance() -> None:
    """Sanity check that default_factory protected us from the classic
    mutable-default bug — each instance must have its own dict."""
    a = SourceRef(
        source_id="a", source_type=SourceType.commercial_api, confidence=0.9,
    )
    b = SourceRef(
        source_id="b", source_type=SourceType.commercial_api, confidence=0.8,
    )
    a.metadata["leaked"] = True
    assert "leaked" not in b.metadata


# ---------------------------------------------------------------------------
# Forbid-extra still active on the extended model
# ---------------------------------------------------------------------------


def test_extra_unknown_field_still_rejected() -> None:
    """Adding fields didn't relax `extra='forbid'`. Unknown wire keys
    must still raise — protects against typos in future producers."""
    with pytest.raises(ValueError):
        SourceRef.model_validate({
            "source_id": "api_football",
            "source_type": "commercial_api",
            "confidence": 0.9,
            "unknown_field_typo": "x",
        })
