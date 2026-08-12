"""Cross-repo trend-contract guard — V1.1 closure (Sprint X finding H1).

tests/fixtures/trend_envelope_v4.json is the committed golden envelope
(canonical copy: insight-protos/contracts/trends/). insight-nexus
vendors the same file and asserts it DECODES; this side asserts Atlas
still EMITS exactly this wire form.

If you change Trend.to_wire(), the publisher envelope shape, or bump
TREND_SCHEMA_VERSION: regenerate the fixture in all three locations
(see the generator snippet in the V1.1 closure report) and run the
Nexus contract suite — both must pass before either repo ships.
"""

from __future__ import annotations

import datetime
import json
import uuid
from pathlib import Path

from atlas.trends.models import (
    TREND_SCHEMA_VERSION,
    Severity,
    Trend,
    TrendCategory,
    TrendType,
)

FIXTURE = Path(__file__).parent / "fixtures" / "trend_envelope_v4.json"


def _golden_trend() -> Trend:
    return Trend(
        trend_id=uuid.UUID("f1e40000-0000-4000-8000-000000000001"),
        trend_type=list(TrendType)[0],
        category=list(TrendCategory)[0],
        agent="market",
        canonical_match_id=uuid.UUID("f1e40000-0000-4000-8000-000000000002"),
        competition_id=uuid.UUID("f1e40000-0000-4000-8000-000000000003"),
        minute=63,
        strength=0.72,
        confidence=0.81,
        severity=Severity.HIGH if hasattr(Severity, "HIGH") else None,
        direction=1,
        window_seconds=600,
        title="Consenso de mercado crescendo",
        summary="Consenso subiu de 50% para 85% em três janelas de observação.",
        signals=["consensus_rise", "multi_book"],
        evidence={"consensus_before": 0.50, "consensus_after": 0.85, "books": 5},
        chart_data={"series": [{"t": 0, "v": 0.5}, {"t": 600, "v": 0.85}]},
        detected_at=datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
        publish_score=0.78,
        publication_tier="priority_publish",
        lifecycle_state="confirmed",
        correlation_ids=["f1e40000-0000-4000-8000-000000000009"],
        meaning="Mercado convergiu rapidamente para o favorito",
        meaning_category="market_consensus",
        meaning_confidence=0.8,
        timeline={
            "instance_id": "f1e40000-0000-4000-8000-00000000000a",
            "previous_states": ["active", "strengthening"],
            "observation_count": 3,
        },
        pattern={"pattern_id": "p-1", "occurrences": 4, "historical_success_rate": 0.75},
        historical_context={
            "confirmed_rate": 0.66,
            "failed_rate": 0.22,
            "expired_rate": 0.12,
            "sample": 41,
        },
        market_memory={
            "occurrences": 12,
            "confirmations": 8,
            "failures": 3,
            "expirations": 1,
            "avg_duration_seconds": 540.0,
            "avg_confidence": 0.74,
            "avg_strength": 0.61,
        },
        competition_context={
            "volatility": 0.4,
            "confidence": 0.7,
            "fragmentation": 0.2,
            "trend_density": 1.6,
        },
        regime="STABLE",
        continuation={
            "expected_duration_seconds": 600.0,
            "continuation_probability": 0.7,
            "termination_probability": 0.3,
            "sample": 33,
        },
    )


def test_emitted_envelope_matches_golden_fixture() -> None:
    """The wire form Atlas publishes equals the committed fixture byte
    for byte (sorted-keys JSON) — any drift forces a deliberate fixture
    regeneration + a Nexus decode check."""
    envelope = {
        "schema_version": TREND_SCHEMA_VERSION,
        "priority": True,
        "trend": _golden_trend().to_wire(),
    }
    emitted = json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert emitted == FIXTURE.read_text(), (
        "Trend wire contract drifted from the golden fixture. Regenerate "
        "the fixture in atlas/protos/nexus AND run insight-nexus "
        "tests/contract before shipping."
    )


def test_schema_version_is_v4() -> None:
    assert TREND_SCHEMA_VERSION == "v4"
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["schema_version"] == TREND_SCHEMA_VERSION
