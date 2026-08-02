"""Intelligence Maturity (Sprint 1.5) — market memory, historical
outcomes, meta trends, competition intelligence, regimes, cross-match,
continuation, Contract V4 and the e2e proofs.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import fakeredis.aioredis
import pytest

from atlas.event_aggregation import InMemoryAggregationStore
from atlas.intelligence.competition import CompetitionIntelligenceEngine
from atlas.intelligence.continuation import ContinuationEngine
from atlas.intelligence.crossmatch import CrossMatchEngine
from atlas.intelligence.enrichment import IntelligenceEnricher
from atlas.intelligence.historical_outcomes import HistoricalOutcomeEngine
from atlas.intelligence.market_memory import MarketMemoryEngine, Scope
from atlas.intelligence.meta_trends import MetaTrendEngine
from atlas.intelligence.regimes import (
    CompetitionRegime,
    RegimeEngine,
    RegimeThresholds,
)
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
from atlas.registry.models import CanonicalMatchRow
import atlas.registry.models  # noqa: F401
from atlas.trends import (
    CorrelatedTrendRepository,
    PublishScoreEngine,
    Trend,
    TrendCategory,
    TrendCorrelationEngine,
    TrendEngine,
    TrendIntelligencePipeline,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendLifecycleState,
    TrendPublisher,
    TrendRepository,
    TrendType,
)
from atlas.trends.correlation import InMemoryRecentTrendStore
from atlas.trends.lifecycle.models import TrendInstance
from atlas.trends.meta import MetaTrendDetector
from atlas.trends.models import TrendInputs
from atlas.trends.timeline import TrendTimelineRepository
from atlas.watchers import IntelligenceWatcher, ObservationSink

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
async def stack():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    redis = fakeredis.aioredis.FakeRedis()
    memory = MarketMemoryEngine(sf)
    enricher = IntelligenceEnricher(
        market_memory=memory,
        historical=HistoricalOutcomeEngine(sf),
        continuation=ContinuationEngine(sf),
        competition=CompetitionIntelligenceEngine(sf),
        regimes=RegimeEngine(sf),
        cache_seconds=0.0,  # tests want fresh aggregates every call
    )
    pipeline = TrendIntelligencePipeline(
        engine=TrendEngine(cooldown_store=None),
        lifecycle_engine=TrendLifecycleEngine(),
        lifecycle_repository=TrendLifecycleRepository(sf),
        correlation_engine=TrendCorrelationEngine(
            InMemoryRecentTrendStore(), cooldown_store=InMemoryAggregationStore()
        ),
        correlation_repository=CorrelatedTrendRepository(sf),
        scoring_engine=PublishScoreEngine(),
        trend_repository=TrendRepository(sf),
        publisher=TrendPublisher(redis, stream="insight:stream:trends"),
        timeline_repository=TrendTimelineRepository(sf),
        intelligence_enricher=enricher,
    )
    try:
        yield sf, redis, pipeline, memory, enricher
    finally:
        await redis.aclose()
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def closed_instance(
    *,
    match_id=None,
    trend_type=TrendType.pressure_building,
    state=TrendLifecycleState.CONFIRMED,
    direction=0,
    minutes=20,
    confidences=(0.7, 0.8),
    strengths=(0.5, 0.6),
) -> TrendInstance:
    return TrendInstance(
        instance_id=uuid4(),
        canonical_match_id=match_id or uuid4(),
        trend_type=trend_type,
        direction=direction,
        created_at=T0,
        last_seen_at=T0 + timedelta(minutes=minutes),
        current_state=state,
        trend_ids=[str(uuid4())],
        strength_history=list(strengths),
        confidence_history=list(confidences),
        state_history=["active", state.value],
    )


async def seed_outcomes(
    memory: MarketMemoryEngine,
    *,
    trend_type: TrendType,
    competition_id=None,
    confirmed=0,
    failed=0,
    expired=0,
    direction=0,
    match_id=None,
    minutes=20,
) -> None:
    for state, count in (
        (TrendLifecycleState.CONFIRMED, confirmed),
        (TrendLifecycleState.FAILED, failed),
        (TrendLifecycleState.EXPIRED, expired),
    ):
        for _ in range(count):
            await memory.record_closure(
                closed_instance(
                    match_id=match_id or uuid4(),
                    trend_type=trend_type,
                    state=state,
                    direction=direction,
                    minutes=minutes,
                ),
                competition_id=competition_id,
            )


async def seed_match_identity(sf, match_id, home, away, competition_id=None):
    async with sf() as session:
        session.add(CanonicalMatchRow(
            canonical_match_id=match_id,
            competition_id=competition_id,
            home_team=home,
            away_team=away,
            kickoff=T0,
        ))
        await session.commit()


# --- Part 1: market memory -------------------------------------------------------


async def test_market_memory_profile_aggregates_closures(stack) -> None:
    sf, _, _, memory, _ = stack
    comp = uuid4()
    await seed_outcomes(
        memory, trend_type=TrendType.pressure_building,
        competition_id=comp, confirmed=4, failed=1, expired=1, minutes=22,
    )
    profile = await memory.profile(
        TrendType.pressure_building, Scope.competition(comp)
    )
    assert profile.occurrences == 6
    assert profile.confirmations == 4
    assert profile.failures == 1
    assert profile.expirations == 1
    assert profile.avg_duration_seconds == pytest.approx(22 * 60)
    assert profile.avg_confidence == pytest.approx(0.75)
    assert profile.confirmation_rate == pytest.approx(0.8)
    # Global scope sees the same closures.
    global_profile = await memory.profile(
        TrendType.pressure_building, Scope.global_()
    )
    assert global_profile.occurrences == 6


async def test_market_memory_is_replay_safe(stack) -> None:
    sf, _, _, memory, _ = stack
    inst = closed_instance()
    assert await memory.record_closure(inst) is True
    # Replaying the same closure is a no-op.
    assert await memory.record_closure(inst) is False
    profile = await memory.profile(inst.trend_type, Scope.global_())
    assert profile.occurrences == 1


async def test_market_memory_team_scope(stack) -> None:
    sf, _, _, memory, _ = stack
    mid = uuid4()
    await seed_match_identity(sf, mid, "Flamengo", "Palmeiras")
    await memory.record_closure(closed_instance(match_id=mid))
    profile = await memory.profile(
        TrendType.pressure_building, Scope.team("Flamengo")
    )
    assert profile.occurrences == 1
    other = await memory.profile(
        TrendType.pressure_building, Scope.team("Santos")
    )
    assert other.occurrences == 0


# --- Parts 2 + 7: historical outcomes + continuation -------------------------------


async def test_historical_outcome_profile_rates(stack) -> None:
    sf, _, _, memory, _ = stack
    await seed_outcomes(
        memory, trend_type=TrendType.market_conviction,
        confirmed=7, failed=2, expired=1,
    )
    profile = await HistoricalOutcomeEngine(sf).profile(
        TrendType.market_conviction
    )
    assert profile.sample == 10
    assert profile.confirmed_rate == pytest.approx(0.7)
    assert profile.failed_rate == pytest.approx(0.2)
    assert profile.expired_rate == pytest.approx(0.1)


async def test_historical_profile_needs_min_sample(stack) -> None:
    sf, _, _, memory, _ = stack
    await seed_outcomes(memory, trend_type=TrendType.tempo_change, confirmed=2)
    assert await HistoricalOutcomeEngine(sf, min_sample=5).profile(
        TrendType.tempo_change
    ) is None


async def test_continuation_profile(stack) -> None:
    sf, _, _, memory, _ = stack
    await seed_outcomes(
        memory, trend_type=TrendType.market_conviction,
        confirmed=6, failed=2, minutes=38,
    )
    profile = await ContinuationEngine(sf).profile(TrendType.market_conviction)
    assert profile.expected_duration_seconds == pytest.approx(38 * 60)
    assert profile.continuation_probability == pytest.approx(0.75)
    assert profile.termination_probability == pytest.approx(0.25)


# --- e2e proof: historical outcome enrichment + continuation on the wire -----------


async def test_e2e_enrichment_attaches_v4_fields(stack) -> None:
    sf, redis, pipeline, memory, _ = stack
    comp = uuid4()
    await seed_outcomes(
        memory, trend_type=TrendType.pressure_building,
        competition_id=comp, confirmed=7, failed=2, expired=1, minutes=22,
    )
    result = await pipeline.process(TrendInputs(
        canonical_match_id=uuid4(),
        competition_id=comp,
        context={"pressure": 0.75},
        prior_context={"pressure": 0.5},
    ))
    trend = next(
        t for t in result.trends
        if t.trend_type == TrendType.pressure_building
    )
    # Contract V4: schema + fields.
    wire = trend.to_wire()
    assert wire["schema_version"] == "v4"
    assert wire["historical_context"]["confirmed_rate"] == pytest.approx(0.7)
    assert wire["continuation"]["continuation_probability"] == pytest.approx(0.7)
    assert wire["continuation"]["expected_duration_seconds"] == pytest.approx(22 * 60)
    assert wire["market_memory"]["occurrences"] == 10
    # Parts 2 + 7: also mirrored into the evidence.
    assert trend.evidence["historical_outcomes"]["sample"] == 10
    assert trend.evidence["continuation"]["termination_probability"] == pytest.approx(0.3)


async def test_pipeline_records_closures_into_memory(stack) -> None:
    """Lifecycle confirmations flow into the outcome log through the
    pipeline itself (step 2c)."""
    sf, _, pipeline, memory, _ = stack
    mid = uuid4()
    # Open a market_shift story, then reverse it → FAILED closure.
    await pipeline.process(TrendInputs(
        canonical_match_id=mid,
        odds_history=[],
        context=None,
        signals=[],
        # market_shift via market_state detectors is indirect; use
        # direct context-driven pressure trends instead: open...
        prior_context={"pressure": 0.5},
    ))
    # Simpler: drive closures directly through the lifecycle by
    # processing a pressure trend then a goal confirmation.
    await pipeline.process(TrendInputs(
        canonical_match_id=mid,
        context={"pressure": 0.75},
        prior_context={"pressure": 0.5},
    ))
    await pipeline.process(TrendInputs(
        canonical_match_id=mid,
        impact_category="goal",
    ))
    profile = await memory.profile(
        TrendType.pressure_building, Scope.global_()
    )
    assert profile.occurrences == 1
    assert profile.confirmations == 1


# --- Part 4 + 5: competition intelligence + e2e regime change ------------------------


async def test_competition_profile_and_regime_change(stack) -> None:
    sf, _, pipeline, memory, _ = stack
    comp = uuid4()
    repo = TrendRepository(sf)

    def trend(trend_type, category, match_id, confidence=0.8):
        return Trend(
            trend_type=trend_type, category=category,
            canonical_match_id=match_id, competition_id=comp,
            strength=0.6, confidence=confidence, detected_at=T0,
        )

    m1, m2 = uuid4(), uuid4()
    # Calm, confident start: high-confidence market trends only (no
    # category crosses its share threshold).
    for t in (
        trend(TrendType.market_shift, TrendCategory.ninja, m1),
        trend(TrendType.market_consensus_growing, TrendCategory.ninja, m1),
        trend(TrendType.market_shift, TrendCategory.ninja, m2),
        trend(TrendType.market_consensus_growing, TrendCategory.ninja, m2),
    ):
        await repo.record(t)

    engine = CompetitionIntelligenceEngine(sf)
    regimes = RegimeEngine(sf, thresholds=RegimeThresholds())
    profile = await engine.profile(comp)
    assert profile.trends == 4
    assert profile.matches == 2
    assert profile.trend_density == pytest.approx(2.0)
    regime, changed = await regimes.observe(profile)
    assert regime == CompetitionRegime.HIGH_CONFIDENCE
    assert changed is True  # first classification is a change

    # The competition turns volatile: churn trends flood in.
    for t in (
        trend(TrendType.volatility_increase, TrendCategory.ninja, m1),
        trend(TrendType.sharp_market_move, TrendCategory.ninja, m1),
        trend(TrendType.volatility_increase, TrendCategory.ninja, m2),
        trend(TrendType.sharp_market_move, TrendCategory.ninja, m2),
    ):
        await repo.record(t)
    profile2 = await engine.profile(comp)
    regime2, changed2 = await regimes.observe(profile2)
    assert regime2 == CompetitionRegime.VOLATILE
    assert changed2 is True
    # Stable on re-observation (no change → no new history row).
    regime3, changed3 = await regimes.observe(profile2)
    assert regime3 == CompetitionRegime.VOLATILE
    assert changed3 is False
    assert await regimes.current(comp) == CompetitionRegime.VOLATILE


# --- Part 6: cross-match intelligence -------------------------------------------------


async def test_e2e_crossmatch_profile_generation(stack) -> None:
    sf, _, _, memory, _ = stack
    comp = uuid4()
    repo = TrendRepository(sf)
    matches = [uuid4() for _ in range(4)]
    for mid in matches:
        await seed_match_identity(sf, mid, "Flamengo", f"Rival-{mid.hex[:4]}", comp)
        await repo.record(Trend(
            trend_type=TrendType.market_shift, category=TrendCategory.ninja,
            canonical_match_id=mid, competition_id=comp,
            strength=0.6, confidence=0.8, direction=1,
        ))
    # Volatility in two of them.
    for mid in matches[:2]:
        await repo.record(Trend(
            trend_type=TrendType.volatility_increase, category=TrendCategory.ninja,
            canonical_match_id=mid, competition_id=comp,
            strength=0.5, confidence=0.7,
        ))
    cross = CrossMatchEngine(sf)
    team = await cross.team_profile("Flamengo")
    assert team.matches == 4
    assert team.market_shift_matches == 4
    assert team.market_shift_rate == 1.0       # repeatedly causing shifts
    assert team.volatility_matches == 2
    comp_profile = await cross.competition_profile(comp)
    assert comp_profile.matches == 4
    assert comp_profile.volatility_rate == pytest.approx(0.5)


# --- Part 3: meta trends (unit + e2e proofs) -----------------------------------------


def meta_inputs(mid, comp, meta_state) -> TrendInputs:
    return TrendInputs(
        canonical_match_id=mid,
        competition_id=comp,
        context={"intelligence_state": {"meta": meta_state}},
    )


def test_meta_detector_thresholds() -> None:
    mid, comp = uuid4(), uuid4()
    detector = MetaTrendDetector(min_sample=3, estimation_rate=0.7)
    out = detector.detect(meta_inputs(mid, comp, {
        "scope": f"competition:{comp}",
        "teams": [
            {"team": "Flamengo", "toward_samples": 4, "toward_rate": 0.75,
             "against_samples": 0, "against_rate": 0.0},
            {"team": "Santos", "toward_samples": 2, "toward_rate": 1.0,
             "against_samples": 4, "against_rate": 0.75},
        ],
        "volatility_closures": 4, "volatility_matches": 3,
        "confidence_samples": 5, "confidence_failures": 4,
        "sharp_samples": 4, "sharp_reversals": 2,
    }))
    types = {t.trend_type for t in out}
    assert types == {
        TrendType.market_underestimation,      # Flamengo (4 @ 75%)
        TrendType.market_overestimation,       # Santos (4 against @ 75%)
        TrendType.recurring_volatility,        # 4 closures / 3 matches
        TrendType.recurring_confidence_failure,  # 4/5 failed
        TrendType.recurring_sharp_reversal,    # 2/4 reversed
    }
    under = next(t for t in out if t.trend_type == TrendType.market_underestimation)
    assert under.evidence["team"] == "Flamengo"
    assert under.category == TrendCategory.meta
    # Below min_sample → silent (Santos toward_samples=2).
    assert all(
        t.evidence.get("team") != "Santos"
        for t in out if t.trend_type == TrendType.market_underestimation
    )


async def test_e2e_market_underestimation_detection(stack) -> None:
    """Full proof: confirmed directional market closures → meta scan →
    watcher observation → pipeline → MARKET_UNDERESTIMATION trend."""
    sf, _, pipeline, memory, _ = stack
    comp = uuid4()
    anchor = uuid4()
    repo = TrendRepository(sf)
    await repo.record(Trend(
        trend_type=TrendType.market_shift, category=TrendCategory.ninja,
        canonical_match_id=anchor, competition_id=comp,
        strength=0.6, confidence=0.8, direction=1,
    ))
    # Flamengo at home, market repriced toward home 4x, all confirmed.
    for _ in range(4):
        mid = uuid4()
        await seed_match_identity(sf, mid, "Flamengo", "Opponent", comp)
        await memory.record_closure(
            closed_instance(
                match_id=mid, trend_type=TrendType.market_shift,
                state=TrendLifecycleState.CONFIRMED, direction=1,
            ),
            competition_id=comp,
        )

    watcher = IntelligenceWatcher(
        CompetitionIntelligenceEngine(sf), RegimeEngine(sf),
        MetaTrendEngine(sf), CrossMatchEngine(sf),
    )
    observations = await watcher.observe()
    assert len(observations) == 1
    obs = observations[0]
    state = obs.inputs.context["intelligence_state"]
    assert state["meta"]["teams"][0]["team"] == "Flamengo"
    assert state["meta"]["teams"][0]["toward_rate"] == 1.0

    await ObservationSink(pipeline).process(obs)
    stored = await repo.history(anchor)
    under = [t for t in stored if t.trend_type == TrendType.market_underestimation]
    assert under, "MARKET_UNDERESTIMATION must emerge from recurrence"
    assert under[0].evidence["team"] == "Flamengo"
    assert under[0].meaning == "market_repeatedly_underestimating_team"


async def test_e2e_recurring_volatility_detection(stack) -> None:
    """Full proof: volatility closures across matches → watcher →
    RECURRING_VOLATILITY meta trend through the standard pipeline."""
    sf, _, pipeline, memory, _ = stack
    comp = uuid4()
    anchor = uuid4()
    repo = TrendRepository(sf)
    await repo.record(Trend(
        trend_type=TrendType.volatility_increase, category=TrendCategory.ninja,
        canonical_match_id=anchor, competition_id=comp,
        strength=0.5, confidence=0.7,
    ))
    for _ in range(3):
        await memory.record_closure(
            closed_instance(
                trend_type=TrendType.volatility_increase,
                state=TrendLifecycleState.EXPIRED,
            ),
            competition_id=comp,
        )
    watcher = IntelligenceWatcher(
        CompetitionIntelligenceEngine(sf), RegimeEngine(sf),
        MetaTrendEngine(sf), CrossMatchEngine(sf),
    )
    observations = await watcher.observe()
    await ObservationSink(pipeline).process(observations[0])
    stored = await repo.history(anchor)
    assert any(
        t.trend_type == TrendType.recurring_volatility for t in stored
    ), "RECURRING_VOLATILITY must emerge from repeated episodes"


# --- Part 10: enriched correlations ---------------------------------------------------


async def test_structural_volatility_fusion(stack) -> None:
    """RECURRING_VOLATILITY inside a VOLATILE regime fuses into
    STRUCTURAL_VOLATILITY (predicate rule over the V4 regime field)."""
    sf, _, pipeline, memory, _ = stack
    comp = uuid4()
    anchor = uuid4()
    repo = TrendRepository(sf)
    # Make the competition VOLATILE: churn trends dominate.
    for mid in (anchor, uuid4()):
        for tt in (TrendType.volatility_increase, TrendType.sharp_market_move):
            await repo.record(Trend(
                trend_type=tt, category=TrendCategory.ninja,
                canonical_match_id=mid, competition_id=comp,
                strength=0.5, confidence=0.6,
            ))
    regimes = RegimeEngine(sf)
    profile = await CompetitionIntelligenceEngine(sf).profile(comp)
    regime, _ = await regimes.observe(profile)
    assert regime == CompetitionRegime.VOLATILE
    # Volatility recurrence for the meta detector.
    for _ in range(3):
        await memory.record_closure(
            closed_instance(
                trend_type=TrendType.volatility_increase,
                state=TrendLifecycleState.EXPIRED,
            ),
            competition_id=comp,
        )
    watcher = IntelligenceWatcher(
        CompetitionIntelligenceEngine(sf), regimes,
        MetaTrendEngine(sf), CrossMatchEngine(sf),
    )
    observations = await watcher.observe()
    result = await pipeline.process(observations[0].inputs)
    types = {t.trend_type for t in result.trends}
    assert TrendType.recurring_volatility in types
    assert TrendType.structural_volatility in types
    fused = next(t for t in result.trends
                 if t.trend_type == TrendType.structural_volatility)
    assert fused.evidence["regime"] == "VOLATILE"


async def test_strong_historical_alignment_fusion(stack) -> None:
    """market_conviction whose historical confirmation rate > 70%
    fuses into STRONG_HISTORICAL_ALIGNMENT."""
    sf, _, pipeline, memory, _ = stack
    comp = uuid4()
    await seed_outcomes(
        memory, trend_type=TrendType.market_conviction,
        competition_id=comp, confirmed=8, failed=2,
    )
    # Trigger the standard conviction fusion: consensus growing +
    # confidence acceleration in one tick.
    result = await pipeline.process(TrendInputs(
        canonical_match_id=uuid4(),
        competition_id=comp,
        context={"market_state": {
            "consensus_score": 0.85, "bookmaker_count": 5,
            "confidence_score": 0.7, "confidence_velocity": 0.12,
            "sharp_direction": 1,
        }},
        prior_context={"market_state": {"consensus_score": 0.5}},
    ))
    types = {t.trend_type for t in result.trends}
    assert TrendType.market_conviction in types
    assert TrendType.strong_historical_alignment in types
    aligned = next(t for t in result.trends
                   if t.trend_type == TrendType.strong_historical_alignment)
    assert aligned.evidence["historical_confirmed_rate"] == pytest.approx(0.8)


# --- Part 8: context carry-forward ----------------------------------------------------


def test_intelligence_state_carries_forward_in_context() -> None:
    from atlas.context_engine.recompute import recompute_context

    mid = uuid4()
    block = {"regime": "VOLATILE", "competition_profile": {"trends": 9}}
    first = recompute_context(
        canonical_match_id=mid, minute=10, intelligence_state=block,
    )
    assert first["intelligence_state"] == block
    second = recompute_context(canonical_match_id=mid, minute=20, prior=first)
    assert second["intelligence_state"] == block
