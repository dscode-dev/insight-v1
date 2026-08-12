from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atlas.contracts import SourceRef, SourceType
from atlas.intelligence import (
    INTELLIGENCE_SCHEMA_VERSION,
    AtlasIntelligenceReport,
    Coverage,
    Evidence,
    EvidenceType,
    EvidenceWindow,
    HistoricalOutcomeDistribution,
    IntelligenceContext,
    IntelligenceSignal,
    MarketInsight,
    MarketMovement,
    MarketMovementDirection,
    RegimeInsight,
    RegimeType,
    SignalProvider,
    SignalType,
    SimilarityInsight,
    SimilarMatch,
    TrendDirection,
    TrendInsight,
    UncertaintyInsight,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=timezone.utc)


def evidence(description: str = "odds movement") -> Evidence:
    return Evidence(
        evidence_type=EvidenceType.market,
        source="football-data",
        weight=0.8,
        confidence=0.9,
        description=description,
        observed_at=NOW,
    )


def uncertainty() -> UncertaintyInsight:
    return UncertaintyInsight(
        uncertainty_score=0.3,
        missing_signals=["live statistics"],
        low_coverage=True,
        recommendations=["add a corroborating statistics source"],
        created_at=NOW,
    )


def source() -> SourceRef:
    return SourceRef(
        source_id="football-data",
        source_type=SourceType.internal_bot,
        confidence=0.9,
        observed_at=NOW,
    )


def test_signal_is_strict_evidence_first_and_counts_metadata() -> None:
    item = evidence()
    signal = IntelligenceSignal(
        signal_name="favorite_pressure",
        signal_type=SignalType.market,
        strength=0.7,
        confidence=0.8,
        uncertainty=uncertainty(),
        evidence=[item],
        coverage=Coverage(expected=2, observed=1, ratio=0.5, source_count=1),
        sources=[source()],
        created_at=NOW,
    )
    body = signal.model_dump(mode="json")
    assert body["signal_type"] == "market"
    assert body["source_count"] == 1
    assert body["evidence_count"] == 1
    assert "probabilities" not in body
    assert "recommendation" not in body


def test_signal_rejects_source_count_mismatch() -> None:
    with pytest.raises(ValidationError, match="source_count"):
            IntelligenceSignal(
                signal_name="home_form",
                signal_type=SignalType.form,
            strength=0.5,
            confidence=0.5,
            uncertainty=uncertainty(),
            evidence=[],
            coverage=Coverage(expected=1, observed=1, ratio=1.0, source_count=0),
            sources=[source()],
            created_at=NOW,
        )


def test_evidence_and_windows_require_aware_ordered_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
            Evidence(
                evidence_type=EvidenceType.historical,
                source="x",
            weight=1,
            confidence=1,
            description="draw tendency",
            observed_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError, match="must not precede"):
        EvidenceWindow(start=NOW, end=NOW - timedelta(seconds=1))


def test_trend_regime_market_and_similarity_contracts() -> None:
    regime = RegimeInsight(
        regime_type=RegimeType.league,
        confidence=0.8,
        characteristics=["regular season"],
        expected_behavior=["stable home advantage"],
        risk_factors=["missing live statistics"],
    )
    trend = TrendInsight(
        trend_type="draw_trend",
        direction=TrendDirection.rising,
        strength=0.6,
        confidence=0.7,
        evidence=[evidence("draw tendency")],
        regime=regime.regime_id,
        window=EvidenceWindow(start=NOW - timedelta(days=30), end=NOW),
    )
    market = MarketInsight(
        movement=MarketMovement(
            direction=MarketMovementDirection.shortening,
            strength=0.5,
            outcome="home",
        ),
        volatility=0.4,
        disagreement=0.2,
        favorite_pressure=0.6,
        implied_shift=0.04,
        confidence=0.75,
    )
    similarity = SimilarityInsight(
        similar_matches=[
            SimilarMatch(
                match_id=uuid4(),
                competition="premier_league",
                kickoff_at=NOW,
                home="arsenal",
                away="chelsea",
                similarity_score=0.84,
                shared_patterns=["market disagreement"],
                shared_signals=["market_pressure"],
                shared_trends=["market_trend"],
                historical_outcome="DRAW",
                total_goals=2,
            )
        ],
        similarity_score=0.84,
        minimum_similarity=0.84,
        maximum_similarity=0.84,
        similarity_threshold=0.8,
        actual_neighbor_count=1,
        outcome_distribution=HistoricalOutcomeDistribution(
            home_wins=3, draws=2, away_wins=1
        ),
        shared_patterns=["market disagreement"],
        shared_signals=["market_pressure"],
        shared_trends=["market_trend"],
        trend_distribution={"market_trend": 1},
        regime_distribution={"league": 1},
        average_goals=2.0,
        evidence=[evidence("historical similarity")],
        confidence=0.65,
    )
    assert trend.window.seconds == 30 * 24 * 60 * 60
    assert market.movement.direction == MarketMovementDirection.shortening
    assert similarity.outcome_distribution.sample_size == 6


def test_report_is_primary_non_prediction_contract() -> None:
    item = evidence()
    signal = IntelligenceSignal(
        signal_name="scoring_volatility",
        signal_type=SignalType.volatility,
        strength=0.65,
        confidence=0.7,
        uncertainty=uncertainty(),
        evidence=[item],
        coverage=Coverage(expected=1, observed=1, ratio=1.0, source_count=1),
        sources=[source()],
        created_at=NOW,
    )
    report = AtlasIntelligenceReport(
        match_id=uuid4(),
        as_of=NOW,
        signals=[signal],
        evidence=[item],
        uncertainty=uncertainty(),
        created_at=NOW,
    )
    body = report.model_dump(mode="json")
    assert body["schema_version"] == INTELLIGENCE_SCHEMA_VERSION
    assert body["evidence_count"] == 1
    assert body["source_count"] == 1
    forbidden = {"prediction", "probabilities", "winner", "pick", "bet"}
    assert forbidden.isdisjoint(body)
    restored = AtlasIntelligenceReport.model_validate(body)
    assert restored.report_id == report.report_id


def test_report_rejects_duplicate_evidence_identity() -> None:
    item = evidence()
    with pytest.raises(ValidationError, match="evidence_id"):
        AtlasIntelligenceReport(
            as_of=NOW,
            evidence=[item, item],
            uncertainty=uncertainty(),
            created_at=NOW,
        )


def test_provider_protocol_is_structural() -> None:
    class Provider:
        async def signals(
            self, context: IntelligenceContext
        ) -> list[IntelligenceSignal]:
            return []

    assert isinstance(Provider(), SignalProvider)
    context = IntelligenceContext(as_of=NOW)
    assert context.as_of == NOW
