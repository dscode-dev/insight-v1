"""Sprint 1 — named trend engines, Contract V1 enrichment, severity
bands, deterministic templates, and stats-driven momentum inputs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from atlas.odds.models import OddsTick
from atlas.signal_engine import Signal, SignalType
from atlas.trends import (
    HistoricalTrendEngine,
    ImpactTrendEngine,
    MarketTrendEngine,
    MomentumTrendEngine,
    NarrativeTrendEngine,
    Severity,
    Trend,
    TrendCategory,
    TrendEngine,
    TrendInputs,
    TrendType,
    default_engines,
    severity_for,
)
from atlas.trends.contract import render

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


def _tick(match_id, *, bookmaker="bet365", home=1.85, minutes=0) -> OddsTick:
    return OddsTick(
        canonical_event_id=uuid4(),
        provider="the_odds_api",
        competition_id=uuid4(),
        match_id=match_id,
        market="h2h",
        bookmaker=bookmaker,
        home=home,
        draw=3.4,
        away=4.5,
        captured_at=T0 + timedelta(minutes=minutes),
        payload={},
    )


def _inputs(match_id=None, **kw) -> TrendInputs:
    return TrendInputs(canonical_match_id=match_id or uuid4(), **kw)


def _goal_signal(match_id) -> Signal:
    return Signal(
        signal_type=SignalType.GOAL,
        canonical_match_id=match_id,
        confidence=0.9,
        impact="CRITICAL",
    )


# --- severity ----------------------------------------------------------------


def test_severity_bands() -> None:
    assert severity_for(0.1) == Severity.low
    assert severity_for(0.4) == Severity.medium
    assert severity_for(0.7) == Severity.high
    assert severity_for(0.9) == Severity.critical


def test_severity_auto_derived() -> None:
    t = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=uuid4(),
        strength=0.9,
        confidence=0.5,
    )
    assert t.severity == Severity.critical
    # Explicit severity wins over the derived band.
    forced = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=uuid4(),
        strength=0.9,
        confidence=0.5,
        severity=Severity.low,
    )
    assert forced.severity == Severity.low


# --- contract templates ------------------------------------------------------


def test_templates_cover_every_trend_type() -> None:
    """Every TrendType must render a non-empty deterministic (title,
    summary) — no type may reach the wire without text."""
    for trend_type in TrendType:
        t = Trend(
            trend_type=trend_type,
            category=TrendCategory.ninja,  # category irrelevant to render
            canonical_match_id=uuid4(),
            strength=0.5,
            confidence=0.5,
            direction=1,
            evidence={"impact": "CRITICAL", "category": "goal"},
        )
        title, summary = render(t)
        assert title and summary, f"{trend_type.value} rendered empty text"
        # Render twice → identical (deterministic, no randomness).
        assert render(t) == (title, summary)


def test_market_shift_template_uses_evidence() -> None:
    t = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=uuid4(),
        strength=0.6,
        confidence=0.7,
        direction=1,
        evidence={
            "implied_prob_prev": 0.541,
            "implied_prob_now": 0.625,
            "prob_delta": 0.084,
            "bookmaker_count": 3,
        },
    )
    title, summary = render(t)
    assert "home side" in title
    assert "54.1%" in summary and "62.5%" in summary and "8.4pp" in summary


# --- engine isolation + enrichment -------------------------------------------


def test_market_engine_enriches_contract_fields() -> None:
    mid = uuid4()
    history = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.60, minutes=5)]
    trends = MarketTrendEngine().detect(
        _inputs(mid, odds_history=history, signals=[_goal_signal(mid)])
    )
    assert trends, "expected at least market_shift"
    for t in trends:
        assert t.agent == "market"
        assert t.title and t.summary
        assert t.signals == ["GOAL"]
        assert t.severity is not None
    shift = next(t for t in trends if t.trend_type == TrendType.market_shift)
    assert shift.chart_data["kind"] == "implied_probability"
    assert len(shift.chart_data["series"]) == 2


def test_each_engine_only_produces_its_family() -> None:
    mid = uuid4()
    history = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.55, minutes=5)]
    inputs = _inputs(
        mid,
        odds_history=history,
        impact_label="CRITICAL",
        impact_category="goal",
        context={"game_state": "late", "pressure": 0.7},
        prior_context={"game_state": "second_half", "pressure": 0.5},
        features={"sentiment_delta": -0.5, "community_confidence": 0.9},
    )
    family = {
        "market": (MarketTrendEngine(), TrendCategory.ninja),
        "momentum": (MomentumTrendEngine(), TrendCategory.pulse),
        "historical": (HistoricalTrendEngine(), TrendCategory.oracle),
        "impact": (ImpactTrendEngine(), TrendCategory.sentinel),
        "narrative": (NarrativeTrendEngine(), TrendCategory.echo),
    }
    for agent, (engine, category) in family.items():
        trends = engine.detect(inputs)
        for t in trends:
            assert t.category == category, f"{agent} emitted {t.trend_type}"
            assert t.agent == agent


async def test_engine_isolation_one_engine_failing_does_not_blind_others() -> None:
    class Broken:
        def detect(self, inputs: TrendInputs) -> list[Trend]:
            raise RuntimeError("boom")

    from atlas.trends import BaseTrendEngine

    broken = BaseTrendEngine("broken", [Broken()])
    impact = ImpactTrendEngine()
    composer = TrendEngine(engines=[broken, impact])

    trends = await composer.detect(
        _inputs(impact_label="CRITICAL", impact_category="goal")
    )
    assert len(trends) == 1
    assert trends[0].agent == "impact"


def test_default_engines_complete() -> None:
    agents = [e.name for e in default_engines()]
    assert agents == ["market", "momentum", "historical", "impact", "narrative", "meta"]


# --- stats-driven momentum (Sprint 1 inputs) ---------------------------------


def test_dominance_from_match_statistics() -> None:
    from atlas.trends.pulse import DominancePatternDetector

    stats = {
        "possession_home": 72.0,
        "possession_away": 28.0,
        "shots_home": 14.0,
        "shots_away": 3.0,
        "dangerous_attacks_home": 38.0,
        "dangerous_attacks_away": 9.0,
    }
    trends = DominancePatternDetector().detect(_inputs(match_stats=stats))
    assert len(trends) == 1
    t = trends[0]
    assert t.direction == 1
    assert t.evidence["basis"] == "match_stats"
    assert t.evidence["possession_diff"] == 0.44
    assert t.confidence == 0.75  # stat-backed > feature fallback
    # Balanced stats → silent.
    balanced = {
        "possession_home": 50.0, "possession_away": 50.0,
        "shots_home": 5.0, "shots_away": 5.0,
    }
    assert DominancePatternDetector().detect(_inputs(match_stats=balanced)) == []


def test_dominance_falls_back_to_pressure_feature() -> None:
    from atlas.trends.pulse import DominancePatternDetector

    trends = DominancePatternDetector().detect(
        _inputs(features={"pressure_delta": -0.6})
    )
    assert len(trends) == 1
    assert trends[0].evidence["basis"] == "pressure"
    assert trends[0].direction == -1
