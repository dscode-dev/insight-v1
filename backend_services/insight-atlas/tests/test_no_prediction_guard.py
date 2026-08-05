"""Anti-prediction guard coverage across Atlas's REAL public surfaces.

Before this, the deny-list only protected `ContextOutput` — which is not
Atlas's primary output. The trend stream envelope
(`insight:stream:trends`, consumed by Nexus → Atrium → Azteca) and the
intelligence report's free-text fields were completely unguarded, and
the existing tests only ever scanned KEY NAMES on ContextOutput, never
values and never these surfaces.

These are negative tests: each asserts a violation is REJECTED. They are
the structural backstop for the platform's hardest product rule.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atlas.contracts.no_prediction import (
    assert_no_prediction_keys,
    assert_no_prediction_phrases,
    scan_payload,
)
from atlas.intelligence.contracts import (
    ConfidenceExplanation,
    ConflictInsight,
    Evidence,
    EvidenceType,
    RegimeInsight,
    RegimeType,
)
from atlas.trends.models import Trend, TrendCategory, TrendType

NOW = datetime.now(timezone.utc)


# --- the primitives ---------------------------------------------------------


def test_key_scan_rejects_forbidden_key():
    with pytest.raises(ValueError, match="deny-list"):
        assert_no_prediction_keys({"win_probability": 0.72}, where="test")


def test_key_scan_is_exact_not_substring():
    # `expected_lineup` must NOT collide with `expected_return`.
    assert_no_prediction_keys({"expected_lineup": "4-3-3"}, where="test")
    assert_no_prediction_keys({"market_entropy": 0.5}, where="test")


def test_phrase_scan_rejects_forecast_language():
    with pytest.raises(ValueError, match="forbidden phrase"):
        assert_no_prediction_phrases("Probabilidade de vitoria: 72%", where="test")


def test_scan_payload_recurses_into_nested_structures():
    with pytest.raises(ValueError, match="deny-list"):
        scan_payload({"outer": {"inner": {"bet_recommendation": "home"}}}, where="test")
    with pytest.raises(ValueError, match="deny-list"):
        scan_payload({"list": [{"pick": "home"}]}, where="test")


# --- Trend: the real wire contract -----------------------------------------


def _trend(**kw):
    base = dict(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=uuid4(),
        confidence=0.8,
        strength=0.7,
    )
    base.update(kw)
    return Trend(**base)


def test_trend_accepts_legitimate_market_evidence():
    """Odds-derived implied probabilities are someone else's number,
    faithfully described — explicitly legitimate, must NOT be blocked."""
    t = _trend(evidence={
        "implied_home_probability": 0.52,
        "fair_probabilities": {"home": 0.5, "draw": 0.28, "away": 0.22},
        "market_entropy": 0.91,
        "consensus_score": 0.85,
    })
    assert t.evidence["implied_home_probability"] == 0.52


def test_trend_rejects_prediction_key_in_evidence():
    with pytest.raises((ValueError, ValidationError), match="deny-list"):
        _trend(evidence={"win_probability": 0.72})


def test_trend_rejects_nested_prediction_key_in_evidence():
    with pytest.raises((ValueError, ValidationError), match="deny-list"):
        _trend(evidence={"model": {"bet_recommendation": "back home"}})


def test_trend_rejects_forecast_phrase_in_summary():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        _trend(summary="O time da casa vai vencer esta partida")


def test_trend_rejects_forecast_phrase_in_title():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        _trend(title="Aposta segura detectada")


# --- Intelligence report text surfaces --------------------------------------


def test_evidence_rejects_forecast_phrase_in_description():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        Evidence(
            evidence_type=EvidenceType.market,
            source="market engine",
            weight=0.9,
            confidence=0.8,
            description="Nossa prediction: probabilidade de vitoria 72%",
            observed_at=NOW,
        )


def test_evidence_rejects_prediction_key_in_attributes():
    with pytest.raises((ValueError, ValidationError), match="deny-list"):
        Evidence(
            evidence_type=EvidenceType.market,
            source="market engine",
            weight=0.9,
            confidence=0.8,
            description="descriptive text",
            observed_at=NOW,
            attributes={"expected_return": 1.4},
        )


def test_conflict_insight_rejects_forecast_phrase():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        ConflictInsight(
            conflict_id="c1",
            severity=0.5,
            description="aposta segura no mandante",
            uncertainty_effect=0.2,
        )


def test_confidence_explanation_rejects_forecast_phrase():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        ConfidenceExplanation(
            level="high",
            score=0.9,
            positive_factors=["sure thing given the sample"],
        )


def test_regime_insight_rejects_forecast_phrase():
    with pytest.raises((ValueError, ValidationError), match="forbidden phrase"):
        RegimeInsight(
            regime_type=RegimeType.league,
            confidence=0.8,
            expected_behavior=["o mandante vai ganhar"],
        )


def test_legitimate_descriptive_text_is_accepted():
    """Guard must not be trigger-happy on ordinary descriptive output."""
    ev = Evidence(
        evidence_type=EvidenceType.historical,
        source="deterministic historical memory",
        weight=0.9,
        confidence=0.8,
        description="42 similar prior contexts; mean similarity 87.3%",
        observed_at=NOW,
        attributes={"strictly_prior": True, "actual_neighbor_count": 42},
    )
    assert ev.confidence == 0.8
