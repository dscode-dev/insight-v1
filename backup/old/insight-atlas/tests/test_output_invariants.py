"""Negative-space tests — Atlas must never produce forbidden outputs.

These tests don't assert what the service emits — they assert what it
*cannot* emit. The ContextOutput schema is the chokepoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atlas.inference.output import ContextOutput, Factor


def test_context_output_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ContextOutput.model_validate(
            {
                "match_id": str(uuid4()),
                "family": "classifier",
                "context_confidence": 0.6,
                "headline": "x",
                "feature_schema_version": 1,
                "win_probability": 0.78,  # forbidden field
            }
        )


def test_context_output_requires_confidence_range() -> None:
    with pytest.raises(ValidationError):
        ContextOutput(
            match_id=uuid4(),
            family="anomaly",
            context_confidence=1.5,  # out of range
            headline="x",
            feature_schema_version=1,
        )


def test_factor_serialises_to_well_known_keys() -> None:
    f = Factor(feature="pressure_delta", contribution=0.42)
    payload = f.model_dump(mode="json")
    assert set(payload.keys()) == {"feature", "contribution"}
    assert payload["feature"] == "pressure_delta"


def test_headline_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ContextOutput(
            match_id=uuid4(),
            family="anomaly",
            context_confidence=0.5,
            headline="x" * 200,  # >140
            feature_schema_version=1,
        )


def test_generated_at_must_be_tz_aware() -> None:
    naive = datetime.utcnow()
    with pytest.raises(ValidationError):
        ContextOutput(
            match_id=uuid4(),
            family="anomaly",
            context_confidence=0.5,
            headline="x",
            feature_schema_version=1,
            generated_at=naive,
        )


def test_generated_at_tz_aware_passes() -> None:
    out = ContextOutput(
        match_id=uuid4(),
        family="anomaly",
        context_confidence=0.5,
        headline="x",
        feature_schema_version=1,
        generated_at=datetime.now(timezone.utc),
    )
    assert out.context_confidence == 0.5
