"""Sprint 2 Part A — interpretation layer, trend timeline, pattern
memory, and Contract V3 compatibility.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from atlas.event_aggregation import InMemoryAggregationStore
from atlas.patterns import PatternMemory, pattern_key
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.trends import (
    CorrelatedTrendRepository,
    PublishScoreEngine,
    Trend,
    TrendCategory,
    TrendCorrelationEngine,
    TrendEngine,
    TrendInputs,
    TrendIntelligencePipeline,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendLifecycleState,
    TrendPublisher,
    TrendRepository,
    TrendType,
)
from atlas.trends.correlation import InMemoryRecentTrendStore
from atlas.trends.interpretation import MEANING_MAP, MeaningCategory, interpret
from atlas.trends.lifecycle.models import TrendInstance
from atlas.trends.models import CATEGORY_OF

import fakeredis.aioredis

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


# --- A1: interpretation -------------------------------------------------------


def test_meaning_map_is_total() -> None:
    """Every TrendType must interpret — no type reaches the wire
    without a meaning."""
    assert set(MEANING_MAP) == set(TrendType)


def test_spec_meanings() -> None:
    cases = {
        TrendType.market_conviction: "market_confidence_increasing",
        TrendType.imminent_breakthrough: "sustained_pressure_near_conversion",
        TrendType.risk_escalation: "instability_increasing",
        TrendType.narrative_divergence: "public_and_market_disagreement",
        TrendType.pressure_building: "attacking_pressure_accumulating",
        TrendType.dominance_pattern: "competitive_control_emerging",
    }
    for trend_type, expected in cases.items():
        meaning, _ = MEANING_MAP[trend_type]
        assert meaning == expected, trend_type


def test_interpret_is_deterministic_and_reproducible() -> None:
    t = Trend(
        trend_type=TrendType.market_conviction,
        category=TrendCategory.fusion,
        canonical_match_id=uuid4(),
        strength=0.7,
        confidence=0.85,
    )
    first = interpret(t)
    second = interpret(t)
    assert first == second
    assert first.meaning == "market_confidence_increasing"
    assert first.meaning_category == MeaningCategory.market_behavior
    assert first.meaning_confidence == 0.85


def test_contract_v3_wire_backward_compatible() -> None:
    t = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=uuid4(),
        strength=0.5,
        confidence=0.8,
        meaning="market_sentiment_shifting",
        meaning_category="market_behavior",
        meaning_confidence=0.8,
        timeline={"previous_states": ["active"]},
        pattern={"pattern_id": "x", "occurrences": 3},
    )
    wire = t.to_wire()
    assert wire["schema_version"] == "v4"
    # Every v1 + v2 key preserved.
    for key in (
        "trend_id", "trend_type", "agent", "confidence", "severity",
        "competition_id", "match_id", "created_at", "title", "summary",
        "signals", "metrics", "chart_data",
        "publish_score", "publication_tier", "lifecycle_state",
        "correlation_ids",
        # v3:
        "meaning", "meaning_category", "meaning_confidence",
        "timeline", "pattern",
    ):
        assert key in wire, key
    assert wire["meaning"] == "market_sentiment_shifting"
    assert wire["timeline"]["previous_states"] == ["active"]


# --- A2: timeline --------------------------------------------------------------


def test_lifecycle_records_state_history_timeline() -> None:
    eng = TrendLifecycleEngine()
    mid = uuid4()

    def _t(strength, confidence):
        return Trend(
            trend_type=TrendType.pressure_building,
            category=CATEGORY_OF[TrendType.pressure_building],
            canonical_match_id=mid,
            strength=strength,
            confidence=confidence,
        )

    touched, _ = eng.process(
        open_instances=[], trends=[_t(0.6, 0.78)], impact_category=None, now=T0
    )
    touched, _ = eng.process(
        open_instances=touched, trends=[_t(0.7, 0.85)], impact_category=None,
        now=T0 + timedelta(minutes=5),
    )
    touched, _ = eng.process(
        open_instances=touched, trends=[], impact_category="goal",
        now=T0 + timedelta(minutes=10),
    )
    inst = touched[0]
    assert inst.state_history == ["active", "strengthening", "confirmed"]
    timeline = inst.timeline()
    assert timeline["previous_states"] == ["active", "strengthening"]
    assert timeline["current_state"] == "confirmed"
    assert timeline["observation_count"] == 2


# --- A3: pattern memory ---------------------------------------------------------


@pytest.fixture
async def session_factory():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield sf
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _terminal_instance(mid, state, *, trend_type=TrendType.market_shift, direction=1):
    inst = TrendInstance.open(
        canonical_match_id=mid, trend_type=trend_type, direction=direction, now=T0
    )
    inst.current_state = state
    return inst


async def test_pattern_memory_counts_and_success_rate(session_factory) -> None:
    pm = PatternMemory(session_factory)
    comp = uuid4()
    # 3 confirmed + 1 failed across different matches, same behaviour.
    for state in (
        TrendLifecycleState.CONFIRMED,
        TrendLifecycleState.CONFIRMED,
        TrendLifecycleState.CONFIRMED,
        TrendLifecycleState.FAILED,
    ):
        await pm.record_outcome(_terminal_instance(uuid4(), state), comp)
    stats = await pm.lookup(comp, TrendType.market_shift, 1)
    assert stats is not None
    assert stats.occurrences == 4
    assert stats.historical_success_rate == 0.75
    assert stats.pattern_id == pattern_key(comp, TrendType.market_shift, 1)


async def test_pattern_memory_ignores_open_instances(session_factory) -> None:
    pm = PatternMemory(session_factory)
    comp = uuid4()
    open_inst = _terminal_instance(uuid4(), TrendLifecycleState.ACTIVE)
    assert await pm.record_outcome(open_inst, comp) is None
    assert await pm.lookup(comp, TrendType.market_shift, 1) is None


async def test_pattern_expired_counts_occurrence_not_rate(session_factory) -> None:
    pm = PatternMemory(session_factory)
    comp = uuid4()
    await pm.record_outcome(
        _terminal_instance(uuid4(), TrendLifecycleState.EXPIRED), comp
    )
    stats = await pm.lookup(comp, TrendType.market_shift, 1)
    assert stats.occurrences == 1
    assert stats.historical_success_rate is None  # nothing resolved yet


# --- pipeline enrichment e2e ----------------------------------------------------


async def test_pipeline_emits_v3_enriched_trends(session_factory) -> None:
    redis = fakeredis.aioredis.FakeRedis()
    pattern_memory = PatternMemory(session_factory)
    pipeline = TrendIntelligencePipeline(
        engine=TrendEngine(
            cooldown_store=InMemoryAggregationStore(), cooldown_seconds=1
        ),
        lifecycle_engine=TrendLifecycleEngine(),
        lifecycle_repository=TrendLifecycleRepository(session_factory),
        correlation_engine=TrendCorrelationEngine(
            InMemoryRecentTrendStore(), cooldown_store=InMemoryAggregationStore()
        ),
        correlation_repository=CorrelatedTrendRepository(session_factory),
        scoring_engine=PublishScoreEngine(),
        trend_repository=TrendRepository(session_factory),
        publisher=TrendPublisher(redis, stream="insight:stream:trends"),
        pattern_memory=pattern_memory,
    )
    mid = uuid4()
    comp = uuid4()
    # Seed a known pattern for this competition + behaviour.
    for state in (TrendLifecycleState.CONFIRMED, TrendLifecycleState.FAILED):
        await pattern_memory.record_outcome(
            _terminal_instance(uuid4(), state,
                               trend_type=TrendType.pressure_building,
                               direction=0),
            comp,
        )

    result = await pipeline.process(
        TrendInputs(
            canonical_match_id=mid,
            competition_id=comp,
            context={"pressure": 0.7},
            prior_context={"pressure": 0.5},
        ),
        now=T0,
    )
    pressure = next(
        t for t in result.trends if t.trend_type == TrendType.pressure_building
    )
    # V3: meaning + timeline + pattern all present + persisted.
    assert pressure.meaning == "attacking_pressure_accumulating"
    assert pressure.meaning_category == "match_dynamics"
    assert pressure.meaning_confidence == pressure.confidence
    assert pressure.timeline["current_state"] == "active"
    assert pressure.timeline["previous_states"] == []
    assert pressure.pattern["occurrences"] == 2
    assert pressure.pattern["historical_success_rate"] == 0.5

    stored = await TrendRepository(session_factory).history(mid)
    assert stored[0].meaning == "attacking_pressure_accumulating"
    await redis.aclose()
