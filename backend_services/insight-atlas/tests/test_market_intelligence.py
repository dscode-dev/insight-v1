"""Magnus Absorption (Sprint 1) — market intelligence engines,
detectors, watcher integration, correlations and e2e proofs.

Covers: fair probabilities, consensus growth, fragmentation,
confidence acceleration, volatility increase, sharp market movement —
unit level, through the trend pipeline, and via the watcher path.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import fakeredis.aioredis
import pytest

from atlas.event_aggregation import InMemoryAggregationStore
from atlas.market import (
    MarketStateEngine,
    consensus,
    divergence,
    fair_probabilities,
    market_confidence,
    sharp_movement,
    volatility,
)
from atlas.odds.models import OddsTick
from atlas.odds.repository import OddsRepository
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.trends import (
    CorrelatedTrendRepository,
    PublishScoreEngine,
    TrendCorrelationEngine,
    TrendEngine,
    TrendIntelligencePipeline,
    TrendLifecycleEngine,
    TrendLifecycleRepository,
    TrendPublisher,
    TrendRepository,
    TrendType,
)
from atlas.trends.correlation import InMemoryRecentTrendStore
from atlas.trends.market_intelligence import (
    MarketConfidenceTrendDetector,
    MarketConsensusTrendDetector,
    MarketDivergenceDetector,
    MarketVolatilityTrendDetector,
    SharpMarketMoveDetector,
)
from atlas.trends.models import TrendInputs
from atlas.trends.timeline import TrendTimelineRepository
from atlas.watchers import InMemorySeriesStore, MarketWatcher, ObservationSink

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


def tick(match_id, *, home, draw=3.4, away=4.5, minutes=0, bookmaker="bet365"):
    return OddsTick(
        canonical_event_id=uuid4(), provider="the_odds_api",
        competition_id=uuid4(), match_id=match_id, market="h2h",
        bookmaker=bookmaker, home=home, draw=draw, away=away,
        captured_at=T0 + timedelta(minutes=minutes), payload={},
    )


def aligned_books(match_id, *, home=2.0, minutes=0, books=("a", "b", "c")):
    return [tick(match_id, home=home, minutes=minutes, bookmaker=b) for b in books]


# --- ATLAS-SIM-A follow-up: MarketStateEngine reuse-seam regression -----------


def test_compute_matches_standalone_subengine_calls() -> None:
    """MarketStateEngine.compute() now computes latest_fair_probs_by_book/
    fair_prob_points ONCE and passes them into each subengine (they
    previously recomputed the same O(n) scans up to 4x/2x per call).
    This must be numerically identical to calling every subengine
    standalone with no precomputed data."""
    mid = uuid4()
    history = [
        *aligned_books(mid, home=2.00, minutes=0),
        *aligned_books(mid, home=1.90, minutes=5),
        *aligned_books(mid, home=1.70, minutes=10),
        tick(mid, home=1.65, minutes=15, bookmaker="d"),  # a 4th, slightly outlier book
    ]
    state = MarketStateEngine(observe_metrics=False).compute(history)

    assert state.fair == fair_probabilities(history)
    assert state.consensus == consensus(history)
    assert state.divergence == divergence(history)
    assert state.confidence == market_confidence(history)
    assert state.volatility == volatility(history)
    assert state.sharp == sharp_movement(history)


# --- Part 1: fair probability -------------------------------------------------


def test_fair_probabilities_are_margin_free_and_deterministic() -> None:
    mid = uuid4()
    history = aligned_books(mid, home=2.0)
    fair = fair_probabilities(history)
    assert fair is not None
    # Margin removed: probabilities sum to exactly 1.
    assert fair.home + fair.draw + fair.away == pytest.approx(1.0)
    # 1/2.0 = .5, 1/3.4 ≈ .294, 1/4.5 ≈ .222 → overround ≈ 1.016;
    # fair home = .5 / 1.016 ≈ .492.
    assert fair.home == pytest.approx(0.4920, abs=1e-3)
    assert fair.bookmaker_count == 3
    # Reproducible: same input, same output.
    again = fair_probabilities(history)
    assert again == fair


def test_fair_probability_outputs_never_expose_margin() -> None:
    """PRODUCT RULE: no margin/overround/profit key may ever appear in
    the public market_state."""
    mid = uuid4()
    state = MarketStateEngine(observe_metrics=False).compute(
        aligned_books(mid)
    ).as_dict()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield str(k).lower()
                yield from walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from walk(v)

    forbidden = ("margin", "overround", "vig", "juice", "arbitrage",
                 "surebet", "profit")
    for key in walk(state):
        assert not any(bad in key for bad in forbidden), key


def test_fair_probabilities_use_median_against_outlier() -> None:
    mid = uuid4()
    history = aligned_books(mid, home=2.0, books=("a", "b", "c", "d"))
    history.append(tick(mid, home=1.2, bookmaker="outlier"))
    fair = fair_probabilities(history)
    # Median holds near the honest books despite the detached one.
    assert fair.home == pytest.approx(0.4920, abs=1e-2)


# --- Part 2: consensus ----------------------------------------------------------


def test_consensus_strong_agreement_scores_high() -> None:
    mid = uuid4()
    result = consensus(aligned_books(mid))
    assert result is not None
    assert result.score >= 0.95


def test_consensus_fragmented_market_scores_low() -> None:
    mid = uuid4()
    history = [
        tick(mid, home=1.6, bookmaker="a"),
        tick(mid, home=2.4, bookmaker="b"),
        tick(mid, home=3.2, bookmaker="c"),
    ]
    result = consensus(history)
    assert result.score <= 0.2


def test_consensus_requires_two_books() -> None:
    mid = uuid4()
    assert consensus([tick(mid, home=2.0)]) is None


# --- Part 3: divergence --------------------------------------------------------------


def test_divergence_detects_outlier_book() -> None:
    mid = uuid4()
    history = aligned_books(mid, home=2.0)
    history.append(tick(mid, home=1.3, bookmaker="detached"))
    result = divergence(history)
    assert result is not None
    assert result.score > 0.3
    assert "detached" in result.outliers


def test_divergence_aligned_market_scores_low() -> None:
    mid = uuid4()
    result = divergence(aligned_books(mid))
    assert result.score <= 0.05
    assert result.outliers == []


# --- Part 4: confidence ------------------------------------------------------------------


def test_confidence_decisive_unified_market_scores_high() -> None:
    mid = uuid4()
    # Strong favourite (1.25 → fair home ≈ .74) with aligned books.
    history = aligned_books(mid, home=1.25, books=("a", "b", "c"))
    result = market_confidence(history)
    assert result is not None
    assert result.score >= 0.6
    assert result.decisiveness >= 0.7


def test_confidence_velocity_tracks_firming_belief() -> None:
    mid = uuid4()
    history = []
    # Home strengthens snapshot after snapshot for every book.
    for i, home in enumerate([2.4, 2.1, 1.8, 1.55, 1.35]):
        history.extend(aligned_books(mid, home=home, minutes=5 * i))
    result = market_confidence(history)
    assert result.velocity > 0.05
    # And the reverse decays.
    fading = []
    for i, home in enumerate([1.35, 1.55, 1.8, 2.1, 2.4]):
        fading.extend(aligned_books(mid, home=home, minutes=5 * i))
    assert market_confidence(fading).velocity < -0.05


# --- Part 5: volatility ----------------------------------------------------------------------


def test_volatility_churning_market_scores_high() -> None:
    mid = uuid4()
    history = []
    for i, home in enumerate([2.0, 1.7, 2.2, 1.8, 2.3, 1.9]):
        history.extend(aligned_books(mid, home=home, minutes=5 * i))
    result = volatility(history)
    assert result is not None
    assert result.score >= 0.7
    assert result.frequency == 1.0


def test_volatility_still_market_scores_low() -> None:
    mid = uuid4()
    history = []
    for i in range(5):
        history.extend(aligned_books(mid, home=2.0, minutes=5 * i))
    result = volatility(history)
    assert result.score <= 0.05
    assert result.stability == 1.0


# --- Part 6: sharp movement ----------------------------------------------------------------------


def test_sharp_movement_coordinated_fast_move_scores_high() -> None:
    mid = uuid4()
    history = []
    # Every book reprices home sharply downward in price (prob UP),
    # accelerating into the final step.
    for i, home in enumerate([2.2, 2.05, 1.85, 1.55]):
        history.extend(aligned_books(mid, home=home, minutes=5 * i))
    result = sharp_movement(history)
    assert result is not None
    assert result.score >= 0.6
    assert result.direction == 1
    assert result.coordination == 1.0


def test_sharp_movement_flat_market_scores_zero_direction() -> None:
    mid = uuid4()
    history = []
    for i in range(4):
        history.extend(aligned_books(mid, home=2.0, minutes=5 * i))
    result = sharp_movement(history)
    assert result.direction == 0
    assert result.score == 0.0


# --- detectors (Part 8) -------------------------------------------------------------------


def _inputs(mid, now: dict, prior: dict | None = None) -> TrendInputs:
    return TrendInputs(
        canonical_match_id=mid,
        context={"market_state": now},
        prior_context={"market_state": prior} if prior else None,
    )


def test_consensus_detector_growth_and_weakening() -> None:
    mid = uuid4()
    grow = MarketConsensusTrendDetector().detect(_inputs(
        mid, {"consensus_score": 0.8, "bookmaker_count": 4},
        {"consensus_score": 0.5},
    ))
    assert [t.trend_type for t in grow] == [TrendType.market_consensus_growing]
    weak = MarketConsensusTrendDetector().detect(_inputs(
        mid, {"consensus_score": 0.4, "bookmaker_count": 4},
        {"consensus_score": 0.7},
    ))
    assert [t.trend_type for t in weak] == [TrendType.market_consensus_weakening]
    # Below threshold → silent.
    assert MarketConsensusTrendDetector().detect(_inputs(
        mid, {"consensus_score": 0.55}, {"consensus_score": 0.5},
    )) == []


def test_divergence_detector_and_fragmentation() -> None:
    mid = uuid4()
    out = MarketDivergenceDetector().detect(_inputs(
        mid,
        {"divergence_score": 0.7, "consensus_score": 0.2,
         "divergence_outliers": ["x"], "bookmaker_count": 5},
        {"divergence_score": 0.3},
    ))
    types = {t.trend_type for t in out}
    assert types == {TrendType.market_divergence, TrendType.market_fragmentation}


def test_confidence_detector_acceleration_and_decay() -> None:
    mid = uuid4()
    acc = MarketConfidenceTrendDetector().detect(_inputs(
        mid, {"confidence_score": 0.7, "confidence_velocity": 0.12,
              "sharp_direction": 1},
    ))
    assert [t.trend_type for t in acc] == [TrendType.confidence_acceleration]
    dec = MarketConfidenceTrendDetector().detect(_inputs(
        mid, {"confidence_score": 0.4, "confidence_velocity": -0.12},
    ))
    assert [t.trend_type for t in dec] == [TrendType.confidence_decay]


def test_volatility_detector_increase_and_decrease() -> None:
    mid = uuid4()
    up = MarketVolatilityTrendDetector().detect(_inputs(
        mid, {"volatility_score": 0.6}, {"volatility_score": 0.2},
    ))
    assert [t.trend_type for t in up] == [TrendType.volatility_increase]
    down = MarketVolatilityTrendDetector().detect(_inputs(
        mid, {"volatility_score": 0.1}, {"volatility_score": 0.5},
    ))
    assert [t.trend_type for t in down] == [TrendType.volatility_decrease]


def test_sharp_detector_threshold() -> None:
    mid = uuid4()
    hit = SharpMarketMoveDetector().detect(_inputs(
        mid, {"sharp_movement_score": 0.75, "sharp_direction": -1,
              "bookmaker_count": 4},
    ))
    assert [t.trend_type for t in hit] == [TrendType.sharp_market_move]
    assert hit[0].direction == -1
    assert SharpMarketMoveDetector().detect(_inputs(
        mid, {"sharp_movement_score": 0.4},
    )) == []


# --- pipeline e2e (Part 12) ------------------------------------------------------------------


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
    )
    try:
        yield sf, redis, pipeline
    finally:
        await redis.aclose()
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_e2e_consensus_growth_through_pipeline(stack) -> None:
    sf, _, pipeline = stack
    mid = uuid4()
    result = await pipeline.process(_inputs(
        mid, {"consensus_score": 0.85, "bookmaker_count": 5},
        {"consensus_score": 0.5},
    ))
    growing = [t for t in result.trends
               if t.trend_type == TrendType.market_consensus_growing]
    assert len(growing) == 1
    t = growing[0]
    # Deterministic interpretation + meaning + contract rendering.
    assert t.meaning == "market_agreement_strengthening"
    assert t.meaning_category == "market_behavior"
    assert t.title == "Market agreement strengthening"
    assert t.publish_score is not None
    stored = await TrendRepository(sf).history(mid)
    assert any(x.trend_type == TrendType.market_consensus_growing for x in stored)


async def test_e2e_fragmentation_plus_volatility_fuses_market_uncertainty(stack) -> None:
    sf, _, pipeline = stack
    mid = uuid4()
    result = await pipeline.process(_inputs(
        mid,
        {"divergence_score": 0.75, "consensus_score": 0.2,
         "volatility_score": 0.6, "bookmaker_count": 5,
         "divergence_outliers": []},
        {"divergence_score": 0.3, "volatility_score": 0.2},
    ))
    types = {t.trend_type for t in result.trends}
    assert TrendType.market_fragmentation in types
    assert TrendType.volatility_increase in types
    # Part 10: the correlation engine fuses them deterministically.
    assert TrendType.market_uncertainty in types
    fused = next(t for t in result.trends
                 if t.trend_type == TrendType.market_uncertainty)
    assert fused.meaning == "market_uncertainty_rising"


async def test_e2e_sharp_move_plus_pressure_fuses_market_reaction(stack) -> None:
    sf, _, pipeline = stack
    mid = uuid4()
    result = await pipeline.process(TrendInputs(
        canonical_match_id=mid,
        context={
            "pressure": 0.75,
            "market_state": {"sharp_movement_score": 0.8,
                             "sharp_direction": 1, "bookmaker_count": 4},
        },
        prior_context={"pressure": 0.5},
    ))
    types = {t.trend_type for t in result.trends}
    assert TrendType.sharp_market_move in types
    assert TrendType.pressure_building in types
    assert TrendType.market_reaction in types


async def test_e2e_confidence_acceleration_via_watcher(stack) -> None:
    """Full continuous path: odds persisted → MarketWatcher computes
    market_state now/prior → detectors fire confidence + sharp trends
    with NO sports event involved."""
    sf, _, pipeline = stack
    odds = OddsRepository(sf)
    series = InMemorySeriesStore()
    mid = uuid4()
    for i, home in enumerate([2.4, 2.1, 1.8, 1.55, 1.35]):
        for t in aligned_books(mid, home=home, minutes=4 * i):
            await odds.record(t)
    await series.touch_match(mid)

    watcher = MarketWatcher(odds, series, window_seconds=1800)
    observations = await watcher.observe()
    assert len(observations) == 1
    obs = observations[0]
    state = (obs.inputs.context or {}).get("market_state")
    assert state is not None and state["confidence_velocity"] > 0
    # Sharp coordinated repricing earns a synthetic signal.
    kinds = {s.metadata.get("kind") for s in obs.signals}
    assert "sharp_market_move" in kinds

    await ObservationSink(pipeline).process(obs)
    stored = await TrendRepository(sf).history(mid)
    types = {t.trend_type for t in stored}
    assert TrendType.confidence_acceleration in types
    assert TrendType.sharp_market_move in types


async def test_e2e_volatility_increase_via_watcher(stack) -> None:
    """Gradual volatility growth (Part 5 watcher mandate): a quiet
    first half-window then churn → VOLATILITY_INCREASE."""
    sf, _, pipeline = stack
    odds = OddsRepository(sf)
    series = InMemorySeriesStore()
    mid = uuid4()
    # Quiet early window…
    for i in range(4):
        for t in aligned_books(mid, home=2.0, minutes=3 * i):
            await odds.record(t)
    # …then churn in the recent half (window 1800s = 30min; the early
    # ticks sit before latest-15min once these land).
    for j, home in enumerate([1.8, 2.2, 1.75, 2.25, 1.7]):
        for t in aligned_books(mid, home=home, minutes=18 + 3 * j):
            await odds.record(t)
    await series.touch_match(mid)

    watcher = MarketWatcher(odds, series, window_seconds=1800)
    observations = await watcher.observe()
    obs = observations[0]
    now_state = (obs.inputs.context or {}).get("market_state")
    prior_state = (obs.inputs.prior_context or {}).get("market_state")
    assert now_state["volatility_score"] > (prior_state or {}).get(
        "volatility_score", 1.0
    ) or prior_state is None or (
        now_state["volatility_score"] - prior_state["volatility_score"] >= 0.15
    )

    await ObservationSink(pipeline).process(obs)
    stored = await TrendRepository(sf).history(mid)
    assert TrendType.volatility_increase in {t.trend_type for t in stored}


async def test_market_state_carries_forward_in_context(stack) -> None:
    """Part 7: recompute without fresh market data carries the last
    known market_state forward."""
    from atlas.context_engine.recompute import recompute_context

    mid = uuid4()
    state = {"consensus_score": 0.7, "volatility_score": 0.2}
    first = recompute_context(
        canonical_match_id=mid, minute=10, market_state=state,
    )
    assert first["market_state"] == state
    second = recompute_context(
        canonical_match_id=mid, minute=20, prior=first,
    )
    assert second["market_state"] == state
