"""Sprint 1 integration tests — canonical event in, Contract V1 trend
events out.

Composes the real production layers (intelligence pipeline + named
trend engines + persistence + stream publisher) against real backends
(sqlite via aiosqlite, Redis via fakeredis) and drives canonical
envelopes end-to-end:

    envelope → identity → impact → signals → context →
    TrendEngine (5 engines) → trend_events table → insight:stream:trends
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import fakeredis.aioredis
import orjson
import pytest

from atlas.context_engine import (
    CheckpointTracker,
    ContextRecalculationEngine,
    InMemoryCheckpointStore,
    InMemoryMatchContextStore,
)
from atlas.event_aggregation import AggregationEngine, InMemoryAggregationStore
from atlas.event_impact import EventImpactEngine, Impact
from atlas.identity import IdentityRegistry, IdentityResolver
from atlas.intelligence import IntelligencePipeline
from atlas.odds.models import OddsTick
from atlas.odds.repository import OddsRepository
from atlas.publication_engine import PublicationEngine
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.signal_engine import SignalEngine
from atlas.streaming.canonical_consumer import CanonicalEnvelope
from atlas.trends import (
    TrendEngine,
    TrendInputs,
    TrendPublisher,
    TrendRepository,
    TrendType,
)

T0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
TREND_STREAM = "insight:stream:trends"


# --- the composed stack ------------------------------------------------------


class Stack:
    """The production component graph over test backends."""

    def __init__(self, session_factory, redis) -> None:
        self.redis = redis
        self.odds_repository = OddsRepository(session_factory)
        self.pipeline = IntelligencePipeline(
            identity_resolver=IdentityResolver(
                IdentityRegistry(session_factory), tolerance_seconds=5400
            ),
            impact_engine=EventImpactEngine(),
            signal_engine=SignalEngine(),
            aggregation_engine=AggregationEngine(InMemoryAggregationStore()),
            publication_engine=PublicationEngine(
                min_confidence=0.7, min_impact=Impact.HIGH
            ),
            context_engine=ContextRecalculationEngine(
                checkpoint_tracker=CheckpointTracker(InMemoryCheckpointStore())
            ),
            context_store=InMemoryMatchContextStore(),
        )
        self.trend_engine = TrendEngine(
            cooldown_store=InMemoryAggregationStore(), cooldown_seconds=120
        )
        self.trend_repository = TrendRepository(session_factory)
        self.trend_publisher = TrendPublisher(redis, stream=TREND_STREAM)

    async def handle(self, envelope: CanonicalEnvelope, *, minute=None,
                     odds_shift=False, match_stats=None):
        """Mirror of app.py's run_intelligence + run_trends flow."""
        event = envelope.event
        result = await self.pipeline.process(
            event, minute=minute, odds_shift=odds_shift
        )
        payload = event.get("payload") or {}
        odds_history = []
        if event.get("event_type") == "match.odds" and payload.get("match_id"):
            odds_history = await self.odds_repository.history(
                UUID(str(payload["match_id"]))
            )
        inputs = TrendInputs(
            canonical_match_id=result.canonical_match_id,
            competition_id=UUID(str(event["competition_id"])),
            minute=minute,
            context=result.context,
            prior_context=result.prior_context,
            odds_history=odds_history,
            signals=result.signals,
            impact_label=result.classification.impact.label,
            impact_category=result.classification.category,
            match_stats=match_stats,
        )
        trends = await self.trend_engine.detect(inputs)
        for trend in trends:
            await self.trend_repository.record(trend)
        await self.trend_publisher.publish_many(trends)
        return result, trends


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
    try:
        yield Stack(sf, redis)
    finally:
        await redis.aclose()
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


# --- canonical event helpers -------------------------------------------------


def _envelope(event: dict) -> CanonicalEnvelope:
    return CanonicalEnvelope.from_payload(
        json.dumps(
            {
                "schema_version": "v1",
                "stream": "match",
                "idempotency_key": f"{event['event_id']}::candidate",
                "event": event,
                "published_at": T0.isoformat(),
            }
        ).encode()
    )


def _event(event_type: str, *, competition_id=None, **payload) -> dict:
    return {
        "event_id": str(uuid4()),
        "schema_version": "v1",
        "event_type": event_type,
        "occurred_at": T0.isoformat(),
        "match_id": str(uuid4()),
        "competition_id": str(competition_id or uuid4()),
        "payload": payload or {"k": "v"},
        "source": {"source_id": "api_football", "confidence": 0.92},
        "lineage": [{"source_id": "api_football"}],
        "status": "confirmed",
    }


async def _seed_odds(stack: Stack, odds_match_id, prices: list[float]) -> None:
    for i, price in enumerate(prices):
        await stack.odds_repository.record(
            OddsTick(
                canonical_event_id=uuid4(),
                provider="the_odds_api",
                competition_id=uuid4(),
                match_id=odds_match_id,
                market="h2h",
                bookmaker="bet365",
                home=price,
                draw=3.4,
                away=4.5,
                captured_at=T0 + timedelta(minutes=5 * i),
                payload={},
            )
        )


async def _stream_trends(redis) -> list[dict]:
    entries = await redis.xrange(TREND_STREAM)
    return [orjson.loads(fields[b"payload"])["trend"] for _, fields in entries]


# --- integration: odds event → market trends on the stream -------------------


async def test_odds_event_produces_market_trends_end_to_end(stack: Stack) -> None:
    odds_match_id = uuid4()
    # Opening 2.20 → 1.60: a large drift with a sharp final move.
    await _seed_odds(stack, odds_match_id, [2.20, 2.18, 2.16, 1.60])

    event = _event(
        "match.odds",
        match_id=str(odds_match_id),
        market="h2h",
        bookmaker="bet365",
        home=1.60,
        provider="the_odds_api",
        home_team="Brazil",
        away_team="Argentina",
        commence_time="2026-06-01T19:00:00Z",
    )
    _, trends = await stack.handle(_envelope(event), odds_shift=True)

    types = {t.trend_type for t in trends}
    assert TrendType.market_shift in types
    assert TrendType.historical_deviation in types

    # On the stream, in Contract V1 form.
    wire = await _stream_trends(stack.redis)
    assert len(wire) == len(trends)
    shift = next(w for w in wire if w["trend_type"] == "market_shift")
    assert shift["agent"] == "market"
    assert shift["severity"] in {"low", "medium", "high", "critical"}
    assert shift["title"] and shift["summary"]
    assert shift["metrics"]["bookmaker_count"] == 1
    assert shift["chart_data"]["kind"] == "implied_probability"
    assert "ODDS_SHIFT" in shift["signals"]

    # And persisted with the same contract fields.
    history = await stack.trend_repository.history(
        UUID(wire[0]["canonical_match_id"])
    )
    assert any(t.trend_type == TrendType.market_shift and t.agent == "market"
               and t.title for t in history)


# --- integration: goal event → impact trend ----------------------------------


async def test_goal_event_produces_impact_trend_end_to_end(stack: Stack) -> None:
    event = _event("match.goal", scorer="external", minute=71)
    _, trends = await stack.handle(_envelope(event), minute=71)

    impact = [t for t in trends if t.trend_type == TrendType.impact_assessment]
    assert len(impact) == 1
    assert impact[0].agent == "impact"
    assert impact[0].severity is not None and impact[0].severity.value == "critical"
    assert "GOAL" in impact[0].signals

    wire = await _stream_trends(stack.redis)
    assessment = next(w for w in wire if w["trend_type"] == "impact_assessment")
    assert assessment["severity"] == "critical"
    assert assessment["match_id"] == assessment["canonical_match_id"]


# --- integration: stats event → momentum trend --------------------------------


async def test_stats_drive_dominance_trend_end_to_end(stack: Stack) -> None:
    event = _event("match.fixture", scheduled_at="2026-06-01T19:00:00Z")
    stats = {
        "possession_home": 70.0, "possession_away": 30.0,
        "shots_home": 12.0, "shots_away": 2.0,
    }
    _, trends = await stack.handle(_envelope(event), minute=30, match_stats=stats)
    dominance = [t for t in trends if t.trend_type == TrendType.dominance_pattern]
    assert len(dominance) == 1
    assert dominance[0].agent == "momentum"
    assert dominance[0].evidence["basis"] == "match_stats"


# --- integration: cooldown holds across the full stack ------------------------


async def test_cooldown_suppresses_repeat_trends_end_to_end(stack: Stack) -> None:
    event = _event("match.goal")
    _, first = await stack.handle(_envelope(event))
    assert any(t.trend_type == TrendType.impact_assessment for t in first)
    # A second goal seconds later for the SAME match: the impact trend
    # is in cooldown → not re-emitted, stream doesn't double up.
    again = _event("match.goal")
    again["payload"] = event["payload"]
    again["match_id"] = event["match_id"]
    _, second = await stack.handle(_envelope(again))
    assert not any(t.trend_type == TrendType.impact_assessment for t in second)


# --- integration: identity unifies the trend timeline -------------------------


async def test_cross_provider_events_share_one_trend_timeline(stack: Stack) -> None:
    comp = uuid4()
    base = {
        "home_team": "Brazil",
        "away_team": "Argentina",
        "commence_time": "2026-06-01T19:00:00Z",
    }
    e1 = _event("match.goal", competition_id=comp, external_event_id="AF1", **base)
    e2 = _event("match.card", competition_id=comp, external_event_id="FD9",
                card="red", **base)
    e2["source"] = {"source_id": "football_data", "confidence": 0.9}

    r1, _ = await stack.handle(_envelope(e1))
    r2, _ = await stack.handle(_envelope(e2))
    assert r1.canonical_match_id == r2.canonical_match_id

    timeline = await stack.trend_repository.history(r1.canonical_match_id)
    agents = {t.agent for t in timeline}
    assert agents == {"impact"}
    assert len(timeline) >= 1
