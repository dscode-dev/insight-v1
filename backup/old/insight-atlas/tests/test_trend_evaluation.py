"""Sprint 1.5 — lifecycle, correlation, publish scoring, and the
end-to-end evaluated pipeline (event → trend → lifecycle → correlation
→ score → publish).
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import fakeredis.aioredis
import orjson
import pytest

from atlas.event_aggregation import InMemoryAggregationStore
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.signal_engine import Signal, SignalType
from atlas.trends import (
    CorrelatedTrendRepository,
    CorrelationType,
    PublicationTier,
    PublishScoreEngine,
    Trend,
    TrendCategory,
    TrendCorrelationEngine,
    TrendEngine,
    TrendInputs,
    TrendIntelligencePipeline,
    TrendInstance,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendLifecycleState,
    TrendPublisher,
    TrendRepository,
    TrendType,
    tier_for,
)
from atlas.trends.correlation import InMemoryRecentTrendStore
from atlas.trends.models import CATEGORY_OF

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


def _trend(
    trend_type: TrendType,
    match_id,
    *,
    strength=0.5,
    confidence=0.7,
    direction=0,
    evidence=None,
    signals=None,
) -> Trend:
    return Trend(
        trend_type=trend_type,
        category=CATEGORY_OF[trend_type],
        agent="test",
        canonical_match_id=match_id,
        strength=strength,
        confidence=confidence,
        direction=direction,
        evidence=evidence or {},
        signals=signals or [],
        detected_at=T0,
    )


# =============================================================================
# PART 1 — Lifecycle
# =============================================================================


def _engine() -> TrendLifecycleEngine:
    return TrendLifecycleEngine(expiry_seconds=1800)


def test_lifecycle_opens_active_then_strengthens() -> None:
    eng = _engine()
    mid = uuid4()
    t1 = _trend(TrendType.pressure_building, mid, strength=0.6, confidence=0.78)
    touched, states = eng.process(
        open_instances=[], trends=[t1], impact_category=None, now=T0
    )
    assert states[str(t1.trend_id)] == TrendLifecycleState.ACTIVE
    inst = touched[0]

    # Reinforcement with rising confidence + strength → STRENGTHENING.
    t2 = _trend(TrendType.pressure_building, mid, strength=0.7, confidence=0.85)
    touched, states = eng.process(
        open_instances=[inst], trends=[t2], impact_category=None,
        now=T0 + timedelta(minutes=5),
    )
    assert states[str(t2.trend_id)] == TrendLifecycleState.STRENGTHENING
    assert touched[0].observation_count == 2
    assert touched[0].confidence_history == [0.78, 0.85]


def test_lifecycle_weakening() -> None:
    eng = _engine()
    mid = uuid4()
    t1 = _trend(TrendType.pressure_building, mid, strength=0.7, confidence=0.85)
    touched, _ = eng.process(open_instances=[], trends=[t1], impact_category=None, now=T0)
    t2 = _trend(TrendType.pressure_building, mid, strength=0.5, confidence=0.7)
    _, states = eng.process(
        open_instances=touched, trends=[t2], impact_category=None,
        now=T0 + timedelta(minutes=5),
    )
    assert states[str(t2.trend_id)] == TrendLifecycleState.WEAKENING


def test_lifecycle_confirmed_by_goal() -> None:
    eng = _engine()
    mid = uuid4()
    t1 = _trend(TrendType.pressure_building, mid, strength=0.7, confidence=0.85)
    touched, _ = eng.process(open_instances=[], trends=[t1], impact_category=None, now=T0)
    # A goal lands on the next tick — the pressure trend confirmed.
    touched, _ = eng.process(
        open_instances=touched, trends=[], impact_category="goal",
        now=T0 + timedelta(minutes=8),
    )
    assert touched[0].current_state == TrendLifecycleState.CONFIRMED
    assert touched[0].confirmed_by == "impact:goal"


def test_lifecycle_confirmed_by_sustained_movement() -> None:
    eng = _engine()
    mid = uuid4()
    insts: list[TrendInstance] = []
    final_state = None
    for i in range(3):
        t = _trend(
            TrendType.market_shift, mid,
            strength=0.5 + 0.05 * i, confidence=0.6 + 0.05 * i, direction=1,
        )
        insts, states = eng.process(
            open_instances=insts, trends=[t], impact_category=None,
            now=T0 + timedelta(minutes=5 * i),
        )
        final_state = states[str(t.trend_id)]
    assert final_state == TrendLifecycleState.CONFIRMED
    assert insts[0].confirmed_by == "sustain:3_observations"


def test_lifecycle_failed_on_reversal() -> None:
    eng = _engine()
    mid = uuid4()
    up = _trend(TrendType.market_shift, mid, direction=1)
    touched, _ = eng.process(open_instances=[], trends=[up], impact_category=None, now=T0)
    # The market flips direction → instance FAILED; a fresh instance
    # opens for the new direction.
    down = _trend(TrendType.market_shift, mid, direction=-1)
    touched, states = eng.process(
        open_instances=touched, trends=[down], impact_category=None,
        now=T0 + timedelta(minutes=5),
    )
    by_id = {str(i.instance_id): i for i in touched}
    failed = [i for i in by_id.values() if i.current_state == TrendLifecycleState.FAILED]
    assert len(failed) == 1 and failed[0].failed_by == "trend:market_shift"
    assert states[str(down.trend_id)] == TrendLifecycleState.ACTIVE


def test_lifecycle_pressure_fails_on_momentum_flip() -> None:
    eng = _engine()
    mid = uuid4()
    pressure = _trend(TrendType.pressure_building, mid)
    touched, _ = eng.process(
        open_instances=[], trends=[pressure], impact_category=None, now=T0
    )
    flip = _trend(
        TrendType.momentum_shift, mid, direction=-1, evidence={"sign_flip": True}
    )
    touched, _ = eng.process(
        open_instances=touched, trends=[flip], impact_category=None,
        now=T0 + timedelta(minutes=5),
    )
    failed = [i for i in touched if i.current_state == TrendLifecycleState.FAILED]
    assert len(failed) == 1
    assert failed[0].trend_type == TrendType.pressure_building


def test_lifecycle_expires_without_reinforcement() -> None:
    eng = _engine()
    mid = uuid4()
    t1 = _trend(TrendType.pressure_building, mid)
    touched, _ = eng.process(open_instances=[], trends=[t1], impact_category=None, now=T0)
    touched, _ = eng.process(
        open_instances=touched, trends=[], impact_category=None,
        now=T0 + timedelta(minutes=31),
    )
    assert touched[0].current_state == TrendLifecycleState.EXPIRED


# =============================================================================
# PART 2 — Correlation
# =============================================================================


def _corr_engine() -> TrendCorrelationEngine:
    return TrendCorrelationEngine(
        InMemoryRecentTrendStore(), cooldown_store=InMemoryAggregationStore()
    )


async def _correlate(eng, mid, trends):
    return await eng.correlate(TrendInputs(canonical_match_id=mid), trends, now=T0)


async def test_market_conviction_requires_direction_agreement() -> None:
    eng = _corr_engine()
    mid = uuid4()
    shift = _trend(TrendType.market_shift, mid, direction=1)
    accel = _trend(TrendType.market_acceleration, mid, direction=1)
    records, fusions, membership = await _correlate(eng, mid, [shift, accel])
    assert [r.correlation_type for r in records] == [CorrelationType.MARKET_CONVICTION]
    assert fusions[0].trend_type == TrendType.market_conviction
    assert fusions[0].category == TrendCategory.fusion
    assert fusions[0].agent == "correlation"
    assert str(records[0].id) in fusions[0].correlation_ids
    assert set(membership) == {str(shift.trend_id), str(accel.trend_id)}

    # Disagreeing directions never correlate.
    eng2 = _corr_engine()
    mid2 = uuid4()
    records, _, _ = await _correlate(
        eng2, mid2,
        [_trend(TrendType.market_shift, mid2, direction=1),
         _trend(TrendType.market_acceleration, mid2, direction=-1)],
    )
    assert records == []


async def test_imminent_breakthrough_and_risk_escalation() -> None:
    eng = _corr_engine()
    mid = uuid4()
    records, fusions, _ = await _correlate(
        eng, mid,
        [_trend(TrendType.pressure_building, mid),
         _trend(TrendType.dominance_pattern, mid, direction=1),
         _trend(TrendType.risk_increase, mid),
         _trend(TrendType.game_state_change, mid)],
    )
    types = {r.correlation_type for r in records}
    assert CorrelationType.IMMINENT_BREAKTHROUGH in types
    assert CorrelationType.RISK_ESCALATION in types
    fusion_types = {f.trend_type for f in fusions}
    assert TrendType.imminent_breakthrough in fusion_types
    assert TrendType.risk_escalation in fusion_types


async def test_narrative_divergence_within_window() -> None:
    eng = _corr_engine()
    mid = uuid4()
    # The two members arrive on DIFFERENT ticks within the window.
    records, _, _ = await _correlate(
        eng, mid, [_trend(TrendType.narrative_conflict, mid)]
    )
    assert records == []
    records, fusions, _ = await _correlate(
        eng, mid, [_trend(TrendType.market_shift, mid, direction=1)]
    )
    assert [r.correlation_type for r in records] == [
        CorrelationType.NARRATIVE_DIVERGENCE
    ]
    assert fusions[0].title  # template rendered


async def test_correlation_cooldown_prevents_refire() -> None:
    eng = _corr_engine()
    mid = uuid4()
    pair = [
        _trend(TrendType.pressure_building, mid),
        _trend(TrendType.dominance_pattern, mid),
    ]
    first, _, _ = await _correlate(eng, mid, pair)
    assert len(first) == 1
    again, _, _ = await _correlate(eng, mid, pair)
    assert again == []


async def test_correlation_confidence_is_weakest_link_plus_bonus() -> None:
    eng = _corr_engine()
    mid = uuid4()
    records, _, _ = await _correlate(
        eng, mid,
        [_trend(TrendType.pressure_building, mid, confidence=0.6, strength=0.7),
         _trend(TrendType.dominance_pattern, mid, confidence=0.9, strength=0.5)],
    )
    assert records[0].confidence == pytest.approx(0.7)  # min + 0.1
    assert records[0].strength == pytest.approx(0.6)    # mean


# =============================================================================
# PART 3 — Publish scoring
# =============================================================================


def test_tier_boundaries() -> None:
    assert tier_for(0.0) == PublicationTier.SUPPRESS
    assert tier_for(0.29) == PublicationTier.SUPPRESS
    assert tier_for(0.30) == PublicationTier.STORE_ONLY
    assert tier_for(0.59) == PublicationTier.STORE_ONLY
    assert tier_for(0.60) == PublicationTier.PUBLISH
    assert tier_for(0.79) == PublicationTier.PUBLISH
    assert tier_for(0.80) == PublicationTier.PRIORITY_PUBLISH
    assert tier_for(1.0) == PublicationTier.PRIORITY_PUBLISH


def test_score_low_suppress() -> None:
    eng = PublishScoreEngine()
    mid = uuid4()
    weak = _trend(TrendType.tempo_change, mid, strength=0.3, confidence=0.4)
    score = eng.score(weak, lifecycle_state=TrendLifecycleState.FAILED)
    # 0.105 + 0.14 + sev low -0.05 + lifecycle -0.30 → clamp ≥ 0.
    assert score.tier == PublicationTier.SUPPRESS
    assert "lifecycle=-0.300" in score.reasoning


def test_score_medium_store_only() -> None:
    eng = PublishScoreEngine()
    mid = uuid4()
    mid_trend = _trend(TrendType.dominance_pattern, mid, strength=0.57, confidence=0.75)
    score = eng.score(mid_trend, lifecycle_state=TrendLifecycleState.ACTIVE)
    assert score.tier == PublicationTier.STORE_ONLY
    assert 0.30 <= score.score < 0.60


def test_score_high_publish() -> None:
    eng = PublishScoreEngine()
    mid = uuid4()
    strong = _trend(
        TrendType.market_shift, mid, strength=0.9, confidence=0.7,
        signals=["ODDS_SHIFT"],
    )
    score = eng.score(strong, lifecycle_state=TrendLifecycleState.STRENGTHENING)
    # 0.315 + 0.245 + sev critical 0.1 + lifecycle 0.1 + signals 0.02 = 0.78
    assert score.tier == PublicationTier.PUBLISH
    assert score.factors["lifecycle"] == 0.10


def test_score_priority() -> None:
    eng = PublishScoreEngine()
    mid = uuid4()
    confirmed = _trend(
        TrendType.impact_assessment, mid, strength=0.95, confidence=0.85,
        signals=["GOAL"],
    )
    score = eng.score(
        confirmed,
        lifecycle_state=TrendLifecycleState.CONFIRMED,
        correlated=True,
        impact_label="CRITICAL",
    )
    assert score.tier == PublicationTier.PRIORITY_PUBLISH
    assert score.score >= 0.80
    # Every contributing factor is auditable.
    for factor in ("strength", "confidence", "severity", "lifecycle",
                   "correlation", "impact", "signals", "historical_importance"):
        assert factor in score.factors, factor


def test_score_stale_age_penalty() -> None:
    eng = PublishScoreEngine(stale_age_seconds=1800)
    mid = uuid4()
    trend = _trend(TrendType.market_shift, mid, strength=0.6, confidence=0.6)
    old_instance = TrendInstance.open(
        canonical_match_id=mid, trend_type=TrendType.market_shift,
        direction=1, now=T0,
    )
    score = eng.score(
        trend,
        lifecycle_state=TrendLifecycleState.ACTIVE,
        instance=old_instance,
        now=T0 + timedelta(minutes=45),
    )
    assert score.factors["age"] == -0.05


# =============================================================================
# PART 4 — End-to-end evaluated pipeline
# =============================================================================


@pytest.fixture
async def evaluated_stack():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    redis = fakeredis.aioredis.FakeRedis()
    pipeline = TrendIntelligencePipeline(
        engine=TrendEngine(
            cooldown_store=InMemoryAggregationStore(), cooldown_seconds=120
        ),
        lifecycle_engine=TrendLifecycleEngine(expiry_seconds=1800),
        lifecycle_repository=TrendLifecycleRepository(sf),
        correlation_engine=TrendCorrelationEngine(
            InMemoryRecentTrendStore(), cooldown_store=InMemoryAggregationStore()
        ),
        correlation_repository=CorrelatedTrendRepository(sf),
        scoring_engine=PublishScoreEngine(),
        trend_repository=TrendRepository(sf),
        publisher=TrendPublisher(redis, stream="insight:stream:trends"),
    )
    try:
        yield pipeline, TrendRepository(sf), CorrelatedTrendRepository(sf), \
            TrendLifecycleRepository(sf), redis
    finally:
        await redis.aclose()
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def _stream(redis) -> list[dict]:
    entries = await redis.xrange("insight:stream:trends")
    return [
        {
            "priority": fields[b"priority"] == b"true",
            **orjson.loads(fields[b"payload"])["trend"],
        }
        for _, fields in entries
    ]


async def test_e2e_goal_priority_published_with_full_audit(evaluated_stack) -> None:
    pipeline, trend_repo, _, lifecycle_repo, redis = evaluated_stack
    mid = uuid4()
    inputs = TrendInputs(
        canonical_match_id=mid,
        impact_label="CRITICAL",
        impact_category="goal",
        signals=[Signal(
            signal_type=SignalType.GOAL, canonical_match_id=mid,
            confidence=0.9, impact="CRITICAL",
        )],
    )
    result = await pipeline.process(inputs, now=T0)

    impact = next(
        t for t in result.trends if t.trend_type == TrendType.impact_assessment
    )
    # Success criteria: every published trend has lifecycle state,
    # correlation context, publish score, publication tier.
    assert impact.publish_score is not None and impact.publish_score >= 0.80
    assert impact.publication_tier == "priority_publish"
    assert impact.lifecycle_state == "active"
    assert impact.correlation_ids == []
    assert impact in result.priority_published

    # On the stream with the priority flag.
    wire = await _stream(redis)
    entry = next(w for w in wire if w["trend_type"] == "impact_assessment")
    assert entry["priority"] is True
    assert entry["publish_score"] >= 0.80
    assert entry["publication_tier"] == "priority_publish"
    assert entry["lifecycle_state"] == "active"

    # Persisted with the same evaluation (full audit trail).
    stored = await trend_repo.history(mid)
    assert stored[0].publication_tier == "priority_publish"
    # Lifecycle instance recorded.
    instances = await lifecycle_repo.history(mid)
    assert len(instances) == 1


async def test_e2e_correlation_imminent_breakthrough(evaluated_stack) -> None:
    pipeline, trend_repo, corr_repo, _, redis = evaluated_stack
    mid = uuid4()
    inputs = TrendInputs(
        canonical_match_id=mid,
        minute=60,
        context={"pressure": 0.75, "game_state": "second_half"},
        prior_context={"pressure": 0.5, "game_state": "second_half"},
        match_stats={
            "possession_home": 70.0, "possession_away": 30.0,
            "shots_home": 12.0, "shots_away": 2.0,
        },
    )
    result = await pipeline.process(inputs, now=T0)

    types = {t.trend_type for t in result.trends}
    assert TrendType.pressure_building in types
    assert TrendType.dominance_pattern in types
    assert TrendType.imminent_breakthrough in types, "fusion is first-class"

    # The correlation record persisted.
    correlations = await corr_repo.history(mid)
    assert [c.correlation_type for c in correlations] == [
        CorrelationType.IMMINENT_BREAKTHROUGH
    ]
    # Member trends carry the correlation id.
    members = [
        t for t in result.trends
        if t.trend_type in (TrendType.pressure_building, TrendType.dominance_pattern)
    ]
    for member in members:
        assert member.correlation_ids == [str(correlations[0].id)]

    # Everything persisted regardless of tier; stream holds only
    # publishable tiers.
    stored = await trend_repo.history(mid)
    assert len(stored) == len(result.trends)
    wire = await _stream(redis)
    assert {w["trend_type"] for w in wire} == {
        t.trend_type.value for t in result.published
    }
    # Dominance alone (medium score) was stored, not streamed.
    dominance = next(t for t in result.trends
                     if t.trend_type == TrendType.dominance_pattern)
    assert dominance.publication_tier in ("store_only", "publish")


async def test_e2e_lifecycle_confirmation_across_ticks(evaluated_stack) -> None:
    pipeline, _, _, lifecycle_repo, _ = evaluated_stack
    mid = uuid4()
    # Tick 1: pressure building detected.
    await pipeline.process(
        TrendInputs(
            canonical_match_id=mid,
            context={"pressure": 0.7}, prior_context={"pressure": 0.5},
        ),
        now=T0,
    )
    # Tick 2: a goal lands — the open pressure instance confirms.
    await pipeline.process(
        TrendInputs(canonical_match_id=mid, impact_label="CRITICAL",
                    impact_category="goal"),
        now=T0 + timedelta(minutes=8),
    )
    instances = await lifecycle_repo.history(mid)
    pressure = [i for i in instances if i.trend_type == TrendType.pressure_building]
    assert pressure[0].current_state == TrendLifecycleState.CONFIRMED
    assert pressure[0].confirmed_by == "impact:goal"


async def test_e2e_suppressed_trend_persists_but_never_streams(evaluated_stack) -> None:
    pipeline, trend_repo, _, _, redis = evaluated_stack
    mid = uuid4()
    # A weak narrative signal with nothing else going on.
    inputs = TrendInputs(
        canonical_match_id=mid,
        features={"sentiment_delta": -0.36},  # just over detector threshold
    )
    result = await pipeline.process(inputs, now=T0)
    assert len(result.trends) == 1
    trend = result.trends[0]
    # strength 0.36 conf 0.6 sev medium → ~0.336 → STORE_ONLY band.
    assert trend.publication_tier in ("suppress", "store_only")
    assert result.published == []
    assert await _stream(redis) == []
    stored = await trend_repo.history(mid)
    assert len(stored) == 1, "audit trail is unconditional"
