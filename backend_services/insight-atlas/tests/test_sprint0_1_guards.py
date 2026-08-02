"""Coverage for Sprint 0.1.

Surfaces:
  * SourceType + SourceRef validation
  * FeatureWindowOrigin enum values
  * FeatureSnapshot.source_confidence computed projection
  * FeatureSnapshot.feature_window_origin propagation
  * ContextOutput.source_confidence + final_confidence
  * ConservativeProductPolicy combine() semantics + clamp + min reducer
  * engagement_rate is GONE from FEATURE_NAMES
  * Schema version default bumped to 2
  * Policy injection — engine can be constructed with a custom policy
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.config.settings import Settings
from atlas.contracts import FeatureWindowOrigin, SourceRef, SourceType
from atlas.features.definitions import FEATURE_NAMES
from atlas.features.snapshot import FeatureSnapshot
from atlas.inference.confidence_policy import (
    DEFAULT_POLICY,
    ConservativeProductPolicy,
)
from atlas.inference.output import ContextOutput

# ---------------------------------------------------------------------------
# SourceType + SourceRef
# ---------------------------------------------------------------------------


def test_source_type_full_taxonomy() -> None:
    """The 8 categories from Sprint 0.1 must all exist as enum members."""
    expected = {
        "official_api",
        "commercial_api",
        "official_club",
        "official_league",
        "trusted_media",
        "internal_bot",
        "community",
        "unknown",
    }
    assert {m.value for m in SourceType} == expected


def test_source_type_candidate_helper() -> None:
    """The candidate-source helper drives quarantine rules — must include
    bot + community + unknown, and must NOT include official_api etc."""
    candidate = SourceType.candidate_sources()
    assert SourceType.internal_bot in candidate
    assert SourceType.community in candidate
    assert SourceType.unknown in candidate
    assert SourceType.official_api not in candidate
    assert SourceType.commercial_api not in candidate


def test_source_ref_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        SourceRef(
            source_id="api_football",
            source_type=SourceType.commercial_api,
            confidence=1.5,
        )
    with pytest.raises(ValueError):
        SourceRef(
            source_id="api_football",
            source_type=SourceType.commercial_api,
            confidence=-0.1,
        )


def test_source_ref_accepts_string_source_type() -> None:
    """str-Enum allows deserialisation from plain strings — verified
    because Sports Data Hub will publish messages with string slugs."""
    ref = SourceRef.model_validate({
        "source_id": "sportmonks",
        "source_type": "commercial_api",
        "confidence": 0.88,
    })
    assert ref.source_type is SourceType.commercial_api


# ---------------------------------------------------------------------------
# FeatureWindowOrigin
# ---------------------------------------------------------------------------


def test_feature_window_origin_values() -> None:
    expected = {"rolling", "historical", "static", "live", "aggregated", "unknown"}
    assert {m.value for m in FeatureWindowOrigin} == expected


# ---------------------------------------------------------------------------
# FeatureSnapshot — sources, source_confidence, feature_window_origin
# ---------------------------------------------------------------------------


def _sources() -> list[SourceRef]:
    return [
        SourceRef(
            source_id="api_football",
            source_type=SourceType.commercial_api,
            confidence=0.95,
        ),
        SourceRef(
            source_id="sportmonks",
            source_type=SourceType.commercial_api,
            confidence=0.88,
        ),
        SourceRef(
            source_id="club_official_bot",
            source_type=SourceType.internal_bot,
            confidence=0.81,
        ),
    ]


def test_snapshot_source_confidence_dict_view_matches_spec_example() -> None:
    snap = FeatureSnapshot(
        match_id=uuid4(),
        ts=datetime.now(timezone.utc),
        features={"pressure_home_5m": 0.7},
        sources=_sources(),
    )
    # Sprint 0.1 spec example was the exact dict below.
    assert snap.source_confidence == {
        "api_football": 0.95,
        "sportmonks": 0.88,
        "club_official_bot": 0.81,
    }


def test_snapshot_serialises_sources_and_window_origin_in_to_json_dict() -> None:
    snap = FeatureSnapshot(
        match_id=uuid4(),
        ts=datetime.now(timezone.utc),
        features={"pressure_home_5m": 0.7},
        sources=_sources(),
        feature_window_origin=FeatureWindowOrigin.historical,
    )
    payload = snap.to_json_dict()
    assert payload["feature_window_origin"] == "historical"
    assert payload["source_confidence"] == snap.source_confidence
    assert len(payload["sources"]) == 3
    assert payload["sources"][0]["source_type"] == "commercial_api"


def test_snapshot_defaults_window_origin_to_rolling() -> None:
    """Worker-driven build path doesn't set window_origin explicitly —
    must default to rolling (the dominant production case)."""
    snap = FeatureSnapshot(
        match_id=uuid4(),
        ts=datetime.now(timezone.utc),
        features={"pressure_home_5m": 0.7},
    )
    assert snap.feature_window_origin is FeatureWindowOrigin.rolling


def test_snapshot_empty_uses_unknown_origin() -> None:
    """`empty()` is the back-fill / pre-tagged path — should signal
    that explicitly via `unknown` rather than impersonating `rolling`."""
    snap = FeatureSnapshot.empty(match_id=uuid4())
    assert snap.feature_window_origin is FeatureWindowOrigin.unknown


# ---------------------------------------------------------------------------
# engagement_rate removal + schema bump
# ---------------------------------------------------------------------------


def test_engagement_rate_gone_from_feature_names() -> None:
    assert "engagement_rate" not in FEATURE_NAMES


def test_feature_schema_version_default_is_2(monkeypatch) -> None:
    """Settings default bumped — fresh service boots on schema v2."""
    # Provide required env so Settings can construct.
    monkeypatch.setenv("INTERNAL_TOKEN", "x" * 32)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ATLAS_ANVIL_API_BASE_URL", "https://gateway.test/v1")
    monkeypatch.setenv("ATLAS_ANVIL_API_KEY", "x" * 32)
    s = Settings()
    assert s.feature_schema_version == 2


# ---------------------------------------------------------------------------
# ConfidencePolicy
# ---------------------------------------------------------------------------


def test_conservative_policy_product_of_three_with_min_reducer() -> None:
    p = ConservativeProductPolicy()
    final = p.combine(
        feature_quality=0.9,
        source_confidence={"a": 0.5, "b": 0.7},
        data_confidence=0.8,
    )
    # min(0.5, 0.7) = 0.5; 0.9 * 0.5 * 0.8 = 0.36
    assert abs(final - 0.36) < 1e-9


def test_conservative_policy_empty_source_dict_neutral() -> None:
    """Empty source_confidence is neutral (1.0), not zero — see policy
    docstring for the safety reasoning."""
    p = ConservativeProductPolicy()
    final = p.combine(
        feature_quality=0.9,
        source_confidence={},
        data_confidence=0.8,
    )
    # 0.9 * 1.0 * 0.8 = 0.72
    assert abs(final - 0.72) < 1e-9


def test_conservative_policy_clamps_above_one() -> None:
    """Numerical noise from classifier softmax can yield 1.0000002. The
    policy must clamp inputs before multiplying so the result stays in
    [0, 1]."""
    p = ConservativeProductPolicy()
    final = p.combine(
        feature_quality=1.0001,
        source_confidence={"a": 1.0002},
        data_confidence=1.0003,
    )
    assert final == pytest.approx(1.0, abs=1e-9)


def test_conservative_policy_accepts_custom_reducer() -> None:
    """The reducer is injectable — verify a mean-reducer plugs in
    cleanly so future policies can override without subclassing."""
    def mean(d: dict[str, float]) -> float:
        return sum(d.values()) / len(d) if d else 1.0

    p = ConservativeProductPolicy(source_reducer=mean)
    final = p.combine(
        feature_quality=1.0,
        source_confidence={"a": 0.4, "b": 0.8},  # mean = 0.6
        data_confidence=1.0,
    )
    assert abs(final - 0.6) < 1e-9


def test_default_policy_is_protocol_compatible() -> None:
    """DEFAULT_POLICY must satisfy the ConfidencePolicy structural type —
    runtime_checkable Protocol lets us assert it directly."""
    from atlas.inference.confidence_policy import ConfidencePolicy
    assert isinstance(DEFAULT_POLICY, ConfidencePolicy)


# ---------------------------------------------------------------------------
# ContextOutput
# ---------------------------------------------------------------------------


def test_context_output_source_confidence_dict_view() -> None:
    out = ContextOutput(
        match_id=uuid4(),
        family="anomaly",
        context_confidence=0.6,
        headline="Movimento incomum detectado",
        feature_schema_version=2,
        sources=_sources(),
        feature_window_origin=FeatureWindowOrigin.live,
        final_confidence=0.42,
    )
    assert out.source_confidence == {
        "api_football": 0.95,
        "sportmonks": 0.88,
        "club_official_bot": 0.81,
    }
    assert out.feature_window_origin is FeatureWindowOrigin.live
    assert out.final_confidence == 0.42


def test_context_output_round_trip_preserves_sources() -> None:
    out = ContextOutput(
        match_id=uuid4(),
        family="anomaly",
        context_confidence=0.6,
        headline="Movimento incomum detectado",
        feature_schema_version=2,
        sources=_sources(),
    )
    dumped = out.model_dump(mode="json")
    restored = ContextOutput.model_validate(dumped)
    assert len(restored.sources) == 3
    assert restored.sources[0].source_type is SourceType.commercial_api
