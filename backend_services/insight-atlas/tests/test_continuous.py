"""Sprint 3.6 — continuous trend intelligence: watchers, synthetic
signals, timeline, coherence, janitor, DLQ replay.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import fakeredis.aioredis
import pytest

from atlas.coherence import StoryCoherenceEngine
from atlas.event_aggregation import InMemoryAggregationStore
from atlas.odds.models import OddsTick
from atlas.odds.repository import OddsRepository
from atlas.ops import DLQReplayService
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.signal_engine import Signal, SignalOrigin, SignalType
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
from atlas.trends.timeline import TrendTimelineRepository
from atlas.watchers import (
    ClusterJanitor,
    InMemorySeriesStore,
    MarketWatcher,
    MatchWatcher,
    NarrativeWatcher,
    ObservationSink,
    RiskWatcher,
    WatcherRegistry,
    WatcherScheduler,
)

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
    pipeline = TrendIntelligencePipeline(
        engine=TrendEngine(cooldown_store=None),  # no cooldown: tests fire repeat trends fast
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


def _tick(match_id, *, home, minutes, bookmaker="bet365"):
    return OddsTick(
        canonical_event_id=uuid4(), provider="the_odds_api",
        competition_id=uuid4(), match_id=match_id, market="h2h",
        bookmaker=bookmaker, home=home, draw=3.4, away=4.5,
        captured_at=T0 + timedelta(minutes=minutes), payload={},
    )


# --- market drift detection ---------------------------------------------------


async def test_market_watcher_detects_gradual_drift(stack) -> None:
    sf, redis, pipeline = stack
    odds = OddsRepository(sf)
    series = InMemorySeriesStore()
    mid = uuid4()
    # Gradual drift: each step tiny, total large (this is exactly what
    # the event path's change gate can miss).
    for i, price in enumerate([2.20, 2.10, 2.00, 1.90, 1.80]):
        await odds.record(_tick(mid, home=price, minutes=5 * i))
    await series.touch_match(mid)

    watcher = MarketWatcher(odds, series, drift_threshold=0.03)
    observations = await watcher.observe()
    assert len(observations) == 1
    signals = observations[0].signals
    # The steady decline earns BOTH a drift signal and (Sprint 1,
    # Magnus Absorption) a sharp-market-move signal.
    assert all(
        s.signal_type == SignalType.ODDS_SHIFT
        and s.origin == SignalOrigin.synthetic
        for s in signals
    )
    drift_signal = next(s for s in signals if "drift" in s.metadata)
    assert drift_signal.metadata["drift"] > 0.03

    # Synthetic pipeline e2e: the observation flows through the SAME
    # trend pipeline and produces real trends.
    sink = ObservationSink(pipeline)
    await sink.process(observations[0])
    stored = await TrendRepository(sf).history(mid)
    types = {t.trend_type for t in stored}
    assert TrendType.historical_deviation in types or TrendType.market_shift in types


# --- pressure buildup detection -------------------------------------------------


async def test_match_watcher_detects_pressure_buildup(stack) -> None:
    sf, redis, pipeline = stack
    series = InMemorySeriesStore()
    mid = uuid4()
    # 55 → 60 → 66 → 71 → 76: no event happened.
    for value in [55, 60, 66, 71, 76]:
        await series.record(mid, "possession_home", float(value))
        await series.record(mid, "possession_away", float(100 - value))

    watcher = MatchWatcher(series, possession_growth=10.0)
    observations = await watcher.observe()
    assert len(observations) == 1
    obs = observations[0]
    assert any(
        s.signal_type == SignalType.PRESSURE_SPIKE and s.origin == SignalOrigin.synthetic
        for s in obs.signals
    )
    # The synthetic observation carries stats so pulse detectors run.
    assert obs.inputs.match_stats["possession_home"] == 76.0

    # Through the standard pipeline: dominance emerges WITHOUT any event.
    await ObservationSink(pipeline).process(obs)
    stored = await TrendRepository(sf).history(mid)
    assert any(t.trend_type == TrendType.dominance_pattern for t in stored)


def test_monotonic_growth_requires_rising_series() -> None:
    from atlas.watchers.watchers import _monotonic_growth
    from atlas.watchers.series import Sample

    rising = [Sample(float(i), v) for i, v in enumerate([55, 60, 66, 71, 76])]
    assert _monotonic_growth(rising, min_points=3) == 21
    dipping = [Sample(float(i), v) for i, v in enumerate([55, 60, 58, 71])]
    assert _monotonic_growth(dipping, min_points=3) is None
    short = rising[:2]
    assert _monotonic_growth(short, min_points=3) is None


# --- risk accumulation ------------------------------------------------------------


async def test_risk_watcher_detects_accumulation() -> None:
    series = InMemorySeriesStore()
    mid = uuid4()
    for _ in range(3):
        await series.record(mid, "risk_yellow_card", 1.0)
    await series.record(mid, "risk_injury", 1.0)
    # 3×1.0 + 1×2.0 = 5.0 ≥ threshold 4.0.
    watcher = RiskWatcher(series, accumulation_threshold=4.0)
    observations = await watcher.observe()
    assert len(observations) == 1
    signal = observations[0].signals[0]
    assert signal.origin == SignalOrigin.synthetic
    assert signal.metadata["accumulation"] == 5.0

    # Below threshold → silent.
    quiet = InMemorySeriesStore()
    await quiet.record(uuid4(), "risk_yellow_card", 1.0)
    assert await RiskWatcher(quiet, accumulation_threshold=4.0).observe() == []


# --- narrative consensus -------------------------------------------------------------


async def test_narrative_watcher_detects_growing_consensus() -> None:
    series = InMemorySeriesStore()
    mid = uuid4()
    for value in [0.5, 0.6, 0.75]:
        await series.record(mid, "community_confidence", value)
    watcher = NarrativeWatcher(series, consensus_growth=0.2)
    observations = await watcher.observe()
    assert len(observations) == 1
    assert observations[0].signals[0].origin == SignalOrigin.synthetic
    assert observations[0].inputs.features["community_confidence"] == 0.75


# --- coherence ------------------------------------------------------------------------


async def test_coherence_calculation(stack) -> None:
    sf, _, _ = stack
    trends_repo = TrendRepository(sf)
    engine = StoryCoherenceEngine(trends_repo, sf, now=lambda: T0)

    def make(match_id, trend_type, category, direction):
        return Trend(
            trend_type=trend_type, category=category,
            canonical_match_id=match_id, strength=0.7, confidence=0.8,
            direction=direction, detected_at=T0,
        )

    # Coherent match: market ↑, match ↑, narrative ↑.
    coherent = uuid4()
    for trend in (
        make(coherent, TrendType.market_shift, TrendCategory.ninja, 1),
        make(coherent, TrendType.momentum_shift, TrendCategory.pulse, 1),
        make(coherent, TrendType.sentiment_shift, TrendCategory.echo, 1),
    ):
        await trends_repo.record(trend)
    high = await engine.compute(coherent)

    # Incoherent match: market ↑, match ↓, narrative ↑.
    incoherent = uuid4()
    for trend in (
        make(incoherent, TrendType.market_shift, TrendCategory.ninja, 1),
        make(incoherent, TrendType.momentum_shift, TrendCategory.pulse, -1),
        make(incoherent, TrendType.sentiment_shift, TrendCategory.echo, 1),
    ):
        await trends_repo.record(trend)
    low = await engine.compute(incoherent)

    assert high.score > low.score
    assert high.components["market"] > 0 and high.components["match"] > 0
    assert low.components["match"] < 0
    # Persisted (upsert) — recompute is deterministic.
    again = await engine.compute(coherent)
    assert again.score == high.score


# --- timeline ---------------------------------------------------------------------------


async def test_timeline_appends_through_pipeline(stack) -> None:
    sf, _, pipeline = stack
    from atlas.trends.models import TrendInputs

    mid = uuid4()
    # Two recalc-driven pressure trends → one story instance, two
    # timeline entries.
    # Second rise is LARGER so both strength and confidence climb
    # (genuine strengthening, not just continuation).
    for prev, now_p in [(0.5, 0.7), (0.7, 0.95)]:
        await pipeline.process(TrendInputs(
            canonical_match_id=mid,
            context={"pressure": now_p},
            prior_context={"pressure": prev},
        ))
    instances = await TrendLifecycleRepository(sf).history(mid)
    assert len(instances) == 1
    timeline = await TrendTimelineRepository(sf).get(instances[0].instance_id)
    assert len(timeline.entries) == 2
    assert timeline.entries[0].trend_type == "pressure_building"
    assert timeline.entries[0].lifecycle_state == "active"
    assert timeline.entries[1].lifecycle_state == "strengthening"
    assert timeline.entries[0].meaning == "attacking_pressure_accumulating"
    # Ordered + append-only.
    assert timeline.entries[0].timestamp <= timeline.entries[1].timestamp


# --- janitor ----------------------------------------------------------------------------


async def test_janitor_expires_stale_instances(stack) -> None:
    sf, _, _ = stack
    repo = TrendLifecycleRepository(sf)
    mid = uuid4()
    stale = TrendInstance.open(
        canonical_match_id=mid, trend_type=TrendType.pressure_building,
        direction=0, now=T0 - timedelta(hours=2),
    )
    stale.strength_history.append(0.6)
    stale.confidence_history.append(0.7)
    fresh = TrendInstance.open(
        canonical_match_id=mid, trend_type=TrendType.market_shift,
        direction=1, now=T0,
    )
    fresh.strength_history.append(0.6)
    fresh.confidence_history.append(0.7)
    await repo.save_many([stale, fresh])

    janitor = ClusterJanitor(sf, inactivity_seconds=1800, now=lambda: T0)
    expired = await janitor.sweep()
    assert expired == 1

    instances = {i.instance_id: i for i in await repo.history(mid)}
    assert instances[stale.instance_id].current_state == TrendLifecycleState.EXPIRED
    assert instances[fresh.instance_id].current_state == TrendLifecycleState.ACTIVE
    # State history audited.
    assert instances[stale.instance_id].state_history[-1] == "expired"
    # Second sweep is a no-op (idempotent).
    assert await janitor.sweep() == 0


# --- watcher isolation ---------------------------------------------------------------------


class _BrokenWatcher:
    def name(self) -> str:
        return "broken"

    def enabled(self) -> bool:
        return True

    async def observe(self):
        raise RuntimeError("boom")


class _CountingWatcher:
    def __init__(self) -> None:
        self.calls = 0

    def name(self) -> str:
        return "counting"

    def enabled(self) -> bool:
        return True

    async def observe(self):
        self.calls += 1
        return []


class _NullSink:
    async def process(self, obs) -> None:  # noqa: ARG002
        return None


async def test_watcher_failure_is_isolated() -> None:
    registry = WatcherRegistry()
    broken = _BrokenWatcher()
    counting = _CountingWatcher()
    registry.register(broken)
    registry.register(counting)
    scheduler = WatcherScheduler(registry, _NullSink(), interval_seconds=1)

    # A failing watcher returns 0 fed observations and never raises.
    assert await scheduler.run_once(broken) == 0
    # The healthy watcher still runs.
    await scheduler.run_once(counting)
    assert counting.calls == 1


async def test_disabled_watcher_never_runs() -> None:
    class Disabled(_CountingWatcher):
        def enabled(self) -> bool:
            return False

    disabled = Disabled()
    scheduler = WatcherScheduler(WatcherRegistry(), _NullSink())
    assert await scheduler.run_once(disabled) == 0
    assert disabled.calls == 0


# --- DLQ replay -----------------------------------------------------------------------------


async def test_dlq_inspect_replay_discard() -> None:
    redis = fakeredis.aioredis.FakeRedis()
    svc = DLQReplayService(redis, dlq_stream="insight:stream:dlq")

    original_payload = json.dumps({"schema_version": "v1", "event": {"k": "v"}})
    body = json.dumps({
        "source_stream": "insight:stream:events:match",
        "source_entry_id": "1-1",
        "reason": "handler_failed",
        "error": "boom",
        "payload": original_payload,
        "failed_at": T0.isoformat(),
    })
    e1 = await redis.xadd("insight:stream:dlq", {"payload": body})
    e2 = await redis.xadd("insight:stream:dlq", {"payload": body})

    # Inspect.
    entries = await svc.inspect()
    assert len(entries) == 2
    assert entries[0].reason == "handler_failed"
    assert entries[0].source_stream == "insight:stream:events:match"

    # Replay: payload returns to the source stream; entry leaves DLQ.
    assert await svc.replay(e1.decode()) is True
    replayed = await redis.xrange("insight:stream:events:match")
    assert len(replayed) == 1
    assert replayed[0][1][b"payload"].decode() == original_payload
    assert len(await svc.inspect()) == 1

    # Discard: entry removed, nothing replayed.
    assert await svc.discard(e2.decode()) is True
    assert await svc.inspect() == []
    assert len(await redis.xrange("insight:stream:events:match")) == 1

    # Missing entries are handled gracefully.
    assert await svc.replay("99-99") is False
    assert await svc.discard("99-99") is False
    await redis.aclose()


# --- synthetic signals carry origin through scoring -------------------------------------------


async def test_synthetic_signals_flow_like_real_ones(stack) -> None:
    sf, _, pipeline = stack
    from atlas.trends.models import TrendInputs

    mid = uuid4()
    synthetic = Signal(
        signal_type=SignalType.PRESSURE_SPIKE, canonical_match_id=mid,
        confidence=0.8, impact="HIGH", origin=SignalOrigin.synthetic,
    )
    result = await pipeline.process(TrendInputs(
        canonical_match_id=mid,
        context={"pressure": 0.75},
        prior_context={"pressure": 0.5},
        signals=[synthetic],
    ))
    pressure = next(
        t for t in result.trends if t.trend_type == TrendType.pressure_building
    )
    # The synthetic signal contributed evidence exactly like an event
    # signal would (signals list + scoring factor).
    assert "PRESSURE_SPIKE" in pressure.signals
    assert "signals" in result.scores[str(pressure.trend_id)].factors
