"""Trend Intelligence Foundation — taxonomy, all five detector
families, engine cooldown, stream publishing, and persistence.
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
from atlas.odds.models import OddsTick
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.trends import (
    CATEGORY_OF,
    Trend,
    TrendCategory,
    TrendEngine,
    TrendInputs,
    TrendPublisher,
    TrendRepository,
    TrendType,
)
from atlas.trends.echo import (
    CommunitySignalDetector,
    NarrativeConflictDetector,
    SentimentShiftDetector,
)
from atlas.trends.ninja import (
    MarketAccelerationDetector,
    MarketAnomalyDetector,
    MarketDisagreementDetector,
    MarketShiftDetector,
)
from atlas.trends.oracle import HistoricalDeviationDetector
from atlas.trends.pulse import (
    DominancePatternDetector,
    MomentumShiftDetector,
    PressureBuildingDetector,
    TempoChangeDetector,
)
from atlas.trends.sentinel import (
    GameStateChangeDetector,
    ImpactAssessmentDetector,
    RiskIncreaseDetector,
)

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


# --- taxonomy ----------------------------------------------------------------


def test_taxonomy_complete() -> None:
    # 17 detector types (Sprint 0) + 4 fusion correlation types (1.5)
    # + 9 market-intelligence types + 2 market fusions (Magnus
    # Absorption) + 5 meta types + 3 maturity fusions (Maturity 1.5).
    assert len(TrendType) == 40
    assert set(CATEGORY_OF) == set(TrendType)
    per_family = {c: 0 for c in TrendCategory}
    for cat in CATEGORY_OF.values():
        per_family[cat] += 1
    assert per_family == {
        TrendCategory.ninja: 13,
        TrendCategory.pulse: 4,
        TrendCategory.oracle: 3,
        TrendCategory.sentinel: 3,
        TrendCategory.echo: 3,
        TrendCategory.fusion: 9,
        TrendCategory.meta: 5,
    }


def test_trend_wire_form_contract_v1() -> None:
    t = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        agent="market",
        canonical_match_id=uuid4(),
        strength=0.5,
        confidence=0.8,
        direction=1,
        title="Market shift toward the home side",
        summary="Consensus moved.",
        signals=["ODDS_SHIFT"],
        evidence={"prob_delta": 0.05},
        chart_data={"kind": "implied_probability", "series": []},
    )
    wire = t.to_wire()
    # Every Contract V1 key must survive in V2 (backward compatible) +
    # the four V2 additions.
    for key in (
        "trend_id", "trend_type", "agent", "confidence", "severity",
        "competition_id", "match_id", "created_at", "title", "summary",
        "signals", "metrics", "chart_data",
        # V2 additions:
        "publish_score", "publication_tier", "lifecycle_state",
        "correlation_ids",
    ):
        assert key in wire, f"contract key missing: {key}"
    assert wire["trend_type"] == "market_shift"
    assert wire["agent"] == "market"
    assert wire["category"] == "ninja"
    assert wire["schema_version"] == "v4"
    # Unevaluated trend: V2 fields default to empty/None.
    assert wire["publish_score"] is None
    assert wire["correlation_ids"] == []
    assert wire["severity"] == "medium"  # strength 0.5 → medium band
    assert wire["metrics"]["prob_delta"] == 0.05
    assert wire["match_id"] == wire["canonical_match_id"]
    assert wire["signals"] == ["ODDS_SHIFT"]
    assert wire["created_at"] == wire["detected_at"]


# --- ninja -------------------------------------------------------------------


def test_market_shift_fires_on_meaningful_move() -> None:
    mid = uuid4()
    # 1.85 → 1.60: implied 0.541 → 0.625 (+0.084 ≥ 0.03 threshold).
    history = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.60, minutes=5)]
    trends = MarketShiftDetector().detect(_inputs(mid, odds_history=history))
    assert len(trends) == 1
    assert trends[0].trend_type == TrendType.market_shift
    assert trends[0].direction == 1
    # Tiny move stays silent.
    quiet = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.86, minutes=5)]
    assert MarketShiftDetector().detect(_inputs(mid, odds_history=quiet)) == []


def test_market_acceleration_needs_speedup() -> None:
    mid = uuid4()
    # Slow drift then a violent move: deltas ~0.003, 0.003, then ~0.08.
    history = [
        _tick(mid, home=1.85, minutes=0),
        _tick(mid, home=1.84, minutes=5),
        _tick(mid, home=1.83, minutes=10),
        _tick(mid, home=1.55, minutes=15),
    ]
    trends = MarketAccelerationDetector().detect(_inputs(mid, odds_history=history))
    assert len(trends) == 1
    assert trends[0].evidence["acceleration_factor"] > 2
    # Steady drift never accelerates.
    steady = [_tick(mid, home=1.85 - 0.01 * i, minutes=5 * i) for i in range(4)]
    assert MarketAccelerationDetector().detect(_inputs(mid, odds_history=steady)) == []


def test_market_disagreement_on_spread() -> None:
    mid = uuid4()
    history = [
        _tick(mid, bookmaker="bet365", home=1.60),
        _tick(mid, bookmaker="pinnacle", home=2.10),
    ]
    trends = MarketDisagreementDetector().detect(_inputs(mid, odds_history=history))
    assert len(trends) == 1
    assert trends[0].evidence["prob_spread"] >= 0.08


def test_market_anomaly_detached_book() -> None:
    mid = uuid4()
    history = [
        _tick(mid, bookmaker="bet365", home=1.85),
        _tick(mid, bookmaker="pinnacle", home=1.87),
        _tick(mid, bookmaker="oddball", home=1.30),  # implied .77 vs ~.54
    ]
    trends = MarketAnomalyDetector().detect(_inputs(mid, odds_history=history))
    assert len(trends) == 1
    assert trends[0].evidence["bookmaker"] == "oddball"


# --- pulse -------------------------------------------------------------------


def test_momentum_shift_sign_flip() -> None:
    trends = MomentumShiftDetector().detect(
        _inputs(features={"momentum_score": 0.4}, prior_features={"momentum_score": -0.3})
    )
    assert len(trends) == 1
    assert trends[0].evidence["sign_flip"] is True
    assert trends[0].direction == 1


def test_pressure_building() -> None:
    trends = PressureBuildingDetector().detect(
        _inputs(context={"pressure": 0.7}, prior_context={"pressure": 0.45})
    )
    assert len(trends) == 1
    # Below the floor → silent even when rising.
    assert (
        PressureBuildingDetector().detect(
            _inputs(context={"pressure": 0.3}, prior_context={"pressure": 0.1})
        )
        == []
    )


def test_tempo_and_dominance() -> None:
    tempo = TempoChangeDetector().detect(
        _inputs(features={"signal_density": 1.2}, prior_features={"signal_density": 0.5})
    )
    assert len(tempo) == 1 and tempo[0].direction == 1
    dom = DominancePatternDetector().detect(_inputs(features={"pressure_delta": -0.6}))
    assert len(dom) == 1 and dom[0].direction == -1


# --- oracle ------------------------------------------------------------------


def test_historical_deviation_from_opening() -> None:
    mid = uuid4()
    history = [
        _tick(mid, home=2.20, minutes=0),    # opening implied ~0.455
        _tick(mid, home=2.00, minutes=10),
        _tick(mid, home=1.60, minutes=20),   # current implied 0.625
    ]
    trends = HistoricalDeviationDetector().detect(_inputs(mid, odds_history=history))
    assert len(trends) == 1
    assert trends[0].trend_type == TrendType.historical_deviation
    assert trends[0].evidence["deviation"] > 0.07


# --- sentinel ----------------------------------------------------------------


def test_impact_assessment_critical_only() -> None:
    det = ImpactAssessmentDetector()
    assert len(det.detect(_inputs(impact_label="CRITICAL", impact_category="goal"))) == 1
    assert det.detect(_inputs(impact_label="MEDIUM", impact_category="substitution")) == []


def test_game_state_change() -> None:
    trends = GameStateChangeDetector().detect(
        _inputs(
            context={"game_state": "late"},
            prior_context={"game_state": "second_half"},
        )
    )
    assert len(trends) == 1
    assert trends[0].evidence == {"from": "second_half", "to": "late"}


def test_risk_increase_late_tight_game() -> None:
    inputs = _inputs(
        minute=80,
        context={
            "pressure": 0.75,
            "contextual_probabilities": {"home": 0.40, "draw": 0.30, "away": 0.30},
        },
        prior_context={"pressure": 0.6},
    )
    trends = RiskIncreaseDetector().detect(inputs)
    assert len(trends) == 1
    # Early in the match → silent regardless of pressure.
    early = _inputs(minute=20, context={"pressure": 0.9}, prior_context={"pressure": 0.5})
    assert RiskIncreaseDetector().detect(early) == []


# --- echo --------------------------------------------------------------------


def test_sentiment_shift_and_community_signal() -> None:
    shift = SentimentShiftDetector().detect(_inputs(features={"sentiment_delta": -0.5}))
    assert len(shift) == 1 and shift[0].direction == -1
    community = CommunitySignalDetector().detect(
        _inputs(features={"community_confidence": 0.85})
    )
    assert len(community) == 1


def test_narrative_conflict_crowd_vs_market() -> None:
    mid = uuid4()
    # Market move UP for home (1.85 → 1.60) while sentiment goes DOWN.
    history = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.60, minutes=5)]
    trends = NarrativeConflictDetector().detect(
        _inputs(mid, odds_history=history, features={"sentiment_delta": -0.4})
    )
    assert len(trends) == 1
    assert trends[0].evidence["market_direction"] == 1
    assert trends[0].evidence["sentiment_direction"] == -1
    # Aligned directions → no conflict.
    aligned = NarrativeConflictDetector().detect(
        _inputs(mid, odds_history=history, features={"sentiment_delta": 0.4})
    )
    assert aligned == []


# --- engine ------------------------------------------------------------------


async def test_engine_runs_all_families_and_cooldown() -> None:
    mid = uuid4()
    engine = TrendEngine(
        cooldown_store=InMemoryAggregationStore(), cooldown_seconds=120
    )
    history = [_tick(mid, home=1.85, minutes=0), _tick(mid, home=1.60, minutes=5)]
    inputs = _inputs(
        mid,
        odds_history=history,
        impact_label="CRITICAL",
        impact_category="goal",
        context={"game_state": "late", "pressure": 0.7},
        prior_context={"game_state": "second_half", "pressure": 0.5},
    )
    first = await engine.detect(inputs)
    types = {t.trend_type for t in first}
    assert TrendType.market_shift in types
    assert TrendType.impact_assessment in types
    assert TrendType.game_state_change in types
    # Same inputs immediately again → cooldown suppresses everything.
    second = await engine.detect(inputs)
    assert second == []


async def test_engine_isolates_failing_detector() -> None:
    class Broken:
        def detect(self, inputs: TrendInputs) -> list[Trend]:
            raise RuntimeError("boom")

    engine = TrendEngine([Broken(), ImpactAssessmentDetector()])
    trends = await engine.detect(_inputs(impact_label="CRITICAL", impact_category="goal"))
    assert len(trends) == 1, "one broken detector must not blind the others"


# --- publisher ---------------------------------------------------------------


async def test_publisher_xadds_wire_envelope() -> None:
    redis = fakeredis.aioredis.FakeRedis()
    pub = TrendPublisher(redis, stream="insight:stream:trends", maxlen=1000)
    trend = Trend(
        trend_type=TrendType.pressure_building,
        category=TrendCategory.pulse,
        canonical_match_id=uuid4(),
        strength=0.7,
        confidence=0.8,
    )
    entry_id = await pub.publish(trend)
    assert entry_id is not None
    entries = await redis.xrange("insight:stream:trends")
    assert len(entries) == 1
    fields = entries[0][1]
    body = orjson.loads(fields[b"payload"])
    assert body["schema_version"] == "v4"
    assert body["priority"] is False
    assert body["trend"]["trend_type"] == "pressure_building"
    assert fields[b"category"] == b"pulse"
    assert fields[b"priority"] == b"false"
    await redis.aclose()


# --- repository --------------------------------------------------------------


@pytest.fixture
async def trend_repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield TrendRepository(sf)
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


async def test_repository_history_and_idempotency(trend_repo: TrendRepository) -> None:
    mid = uuid4()
    t1 = Trend(
        trend_type=TrendType.market_shift,
        category=TrendCategory.ninja,
        canonical_match_id=mid,
        strength=0.4,
        confidence=0.7,
        detected_at=T0,
    )
    t2 = Trend(
        trend_type=TrendType.risk_increase,
        category=TrendCategory.sentinel,
        canonical_match_id=mid,
        strength=0.8,
        confidence=0.75,
        detected_at=T0 + timedelta(minutes=10),
    )
    assert await trend_repo.record(t1) is True
    assert await trend_repo.record(t2) is True
    assert await trend_repo.record(t1) is False, "duplicate trend_id is a no-op"

    history = await trend_repo.history(mid)
    assert [t.trend_type for t in history] == [
        TrendType.market_shift,
        TrendType.risk_increase,
    ]
    only_risk = await trend_repo.history(mid, trend_type=TrendType.risk_increase)
    assert len(only_risk) == 1 and only_risk[0].strength == 0.8
