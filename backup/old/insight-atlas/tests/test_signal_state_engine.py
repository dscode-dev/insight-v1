from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.contracts import SourceRef, SourceType
from atlas.intelligence.contracts import (
    BehaviorType,
    Coverage,
    HistoricalOutcomeDistribution,
    IntelligenceSignal,
    MarketInsight,
    MarketMovement,
    MarketMovementDirection,
    RegimeInsight,
    RegimeType,
    SignalLifecycleStatus,
    SignalType,
    SimilarityInsight,
    TrendDirection,
    TrendInsight,
    UncertaintyInsight,
)
from atlas.intelligence.behavior_engine import BehavioralPatternEngine
from atlas.intelligence.evidence_engine import EvidenceEngine
from atlas.intelligence.kernel import EvidenceWindow
from atlas.intelligence.signal_state_engine import SignalStateEngine

NOW = datetime(2026, 6, 27, tzinfo=timezone.utc)


def _uncertainty() -> UncertaintyInsight:
    return UncertaintyInsight(
        uncertainty_score=0.2,
        missing_signals=[],
        conflicting_signals=[],
        created_at=NOW,
    )


def _signal(
    name: str,
    *,
    signal_type: SignalType = SignalType.market,
    strength: float = 0.7,
    confidence: float = 0.7,
) -> IntelligenceSignal:
    return IntelligenceSignal(
        signal_name=name,
        signal_type=signal_type,
        strength=strength,
        confidence=confidence,
        uncertainty=_uncertainty(),
        coverage=Coverage(expected=2, observed=2, ratio=1.0, source_count=1),
        sources=[
            SourceRef(
                source_id="test",
                source_type=SourceType.internal_bot,
                confidence=0.8,
                observed_at=NOW,
            )
        ],
        created_at=NOW,
    )


def test_signal_state_respects_ttl_and_removes_expired_influence() -> None:
    expired_payload = {
        "signal_id": "expired-draw",
        "signal_key": "draw_tendency",
        "signal_name": "draw_tendency",
        "category": "historical",
        "score": 0.8,
        "confidence": 0.9,
        "weight": 0.8,
        "generated_at": (NOW - timedelta(hours=2)).isoformat(),
        "expires_at": (NOW - timedelta(minutes=1)).isoformat(),
        "explanation": "old draw context",
    }

    summary = SignalStateEngine().evaluate(
        [],
        explorer_signals=[expired_payload],
        as_of=NOW,
        scope_key="ttl-test",
    )

    state = summary.states[0]
    assert state.status is SignalLifecycleStatus.expired
    assert state.active is False
    assert state.effective_confidence == 0
    assert summary.expired_signals == ["draw_tendency"]
    assert summary.strongest_signals == []


def test_signal_state_reinforces_and_conflicts_deterministically() -> None:
    summary = SignalStateEngine().evaluate(
        [
            _signal("favorite_pressure", strength=0.9, confidence=0.85),
            _signal("market_disagreement", strength=0.8, confidence=0.8),
            _signal("market_consensus", strength=0.7, confidence=0.75),
        ],
        as_of=NOW,
        scope_key="reinforcement-conflict",
    )

    assert "favorite_pressure" in summary.reinforced_signals
    assert "favorite_pressure" in summary.conflicting_signals
    favorite = next(
        state for state in summary.states if state.signal_key == "favorite_pressure"
    )
    assert favorite.reinforced is True
    assert favorite.conflicting is True
    assert "market_disagreement" in favorite.conflicts_with
    assert favorite.effective_confidence < favorite.base_confidence + 0.18


def test_signal_state_propagates_low_confidence_parent_to_child() -> None:
    summary = SignalStateEngine().evaluate(
        [
            _signal("favorite_pressure", strength=0.8, confidence=0.8),
            _signal("market_consensus", strength=0.6, confidence=0.2),
        ],
        as_of=NOW,
        scope_key="dependency-test",
    )

    favorite = next(
        state for state in summary.states if state.signal_key == "favorite_pressure"
    )
    assert favorite.effective_confidence < favorite.base_confidence
    assert summary.dependency_explanation["favorite_pressure"]
    assert any(
        edge.parent_signal == "market_consensus"
        for edge in favorite.dependency_edges
    )


def test_behavior_engine_consumes_signal_state_not_raw_signal() -> None:
    evidence = EvidenceEngine()
    signal = _signal(
        "draw_tendency",
        signal_type=SignalType.behavior,
        strength=0.9,
        confidence=0.9,
    )
    state_summary = SignalStateEngine(evidence).evaluate(
        [signal],
        explorer_signals=[
            {
                "signal_key": "draw_tendency",
                "signal_name": "draw_tendency",
                "category": "historical",
                "score": 0.9,
                "confidence": 0.9,
                "weight": 0.8,
                "expires_at": (NOW - timedelta(seconds=1)).isoformat(),
            }
        ],
        as_of=NOW,
        scope_key="behavior-state",
    )
    expired_state = [
        state.model_copy(
            update={
                "status": SignalLifecycleStatus.expired,
                "active": False,
                "expired": True,
                "effective_strength": 0.0,
                "effective_confidence": 0.0,
            }
        )
        for state in state_summary.states
        if state.signal_key == "draw_tendency"
    ]

    patterns = BehavioralPatternEngine(evidence).detect(
        signals=[signal],
        signal_states=expired_state,
        trends=[],
        regime=RegimeInsight(
            regime_type=RegimeType.league,
            confidence=0.8,
        ),
        similarity=SimilarityInsight(
            similarity_score=0.8,
            minimum_similarity=0.8,
            maximum_similarity=0.8,
            similarity_threshold=0.75,
            actual_neighbor_count=0,
            outcome_distribution=HistoricalOutcomeDistribution(
                home_wins=0,
                draws=0,
                away_wins=0,
            ),
            average_goals=2.5,
            confidence=0.6,
        ),
        market=None,
        uncertainty=_uncertainty(),
        scope_key="behavior-state",
    )

    assert all(pattern.type is not BehaviorType.draw_tendency for pattern in patterns)


def test_runtime_report_contains_signal_state_summary() -> None:
    from tests.test_intelligence_runtime import _context, _dataset
    from atlas.intelligence.orchestrator import AtlasIntelligenceOrchestrator

    report = AtlasIntelligenceOrchestrator(_dataset()).execute(_context())

    assert "signal_state_engine" in report.runtime.completed_engines
    assert report.signal_states
    assert report.signal_state is not None
    assert report.strongest_signals == report.signal_state.strongest_signals
    assert isinstance(report.dependency_explanation, dict)


def test_explorer_payload_fields_are_preserved_in_signal_state() -> None:
    payload = {
        "signal_id": "explorer-market-gap",
        "signal_key": "market_disagreement",
        "signal_name": "market_disagreement",
        "category": "market",
        "score": 0.7,
        "confidence": 0.8,
        "weight": 0.75,
        "formula": "spread(opening, closing)",
        "ttl_seconds": 3600,
        "generated_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "metadata": {"source_count": 2, "coverage_ratio": 0.9},
    }

    summary = SignalStateEngine().evaluate(
        [],
        explorer_signals=[payload],
        as_of=NOW,
        scope_key="explorer-payload",
    )

    state = summary.states[0]
    assert state.signal_key == "market_disagreement"
    assert state.metadata["origin"] == "explorer"
    assert state.metadata["formula"] == "spread(opening, closing)"
    assert state.effective_weight == 0.75
    assert state.signal_stability > 0.6


def test_signal_state_supports_trend_objects_without_prediction_language() -> None:
    trend = TrendInsight(
        trend_type="draw_trend",
        direction=TrendDirection.rising,
        strength=0.7,
        confidence=0.8,
        window=EvidenceWindow(start=NOW - timedelta(days=30), end=NOW),
    )
    market = MarketInsight(
        movement=MarketMovement(
            direction=MarketMovementDirection.mixed,
            strength=0.5,
        ),
        volatility=0.2,
        disagreement=0.4,
        favorite_pressure=0.55,
        implied_shift=0.1,
        confidence=0.75,
    )
    assert trend.trend_type == "draw_trend"
    assert market.favorite_pressure == 0.55
