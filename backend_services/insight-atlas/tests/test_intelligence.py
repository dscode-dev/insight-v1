"""Sprint 6.2 real-time intelligence — impact, signals, publication,
aggregation, context recalculation, identity, and the composed pipeline.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.context_engine import (
    CheckpointTracker,
    ContextRecalculationEngine,
    InMemoryCheckpointStore,
    InMemoryMatchContextStore,
    recompute_context,
)
from atlas.event_aggregation import AggregationEngine, InMemoryAggregationStore
from atlas.event_impact import EventImpactEngine, Impact
from atlas.identity import (
    IdentityRegistry,
    IdentityResolver,
    ProviderMatchIdentity,
    mint,
    normalize,
)
from atlas.intelligence import IntelligencePipeline
from atlas.publication_engine import PublicationEngine
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.signal_engine import SignalEngine, SignalType


def _event(event_type: str, **payload) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "competition_id": str(uuid4()),
        "match_id": str(uuid4()),
        "source": {"source_id": "api_football", "confidence": 0.9},
        "payload": payload,
    }


# --- Part 2: Event Impact Engine -------------------------------------------


def test_impact_classifies_taxonomy() -> None:
    eng = EventImpactEngine()
    cases = {
        "match.goal": Impact.CRITICAL,
        "match.result": Impact.CRITICAL,
        "match.penalty": Impact.HIGH,
        "match.odds": Impact.HIGH,
        "match.fixture": Impact.LOW,
        "competition.standings": Impact.LOW,
    }
    for et, want in cases.items():
        c = eng.classify(_event(et))
        assert c.impact == want, f"{et}: {c.impact} != {want}"


def test_impact_card_colour_and_key_sub() -> None:
    eng = EventImpactEngine()
    assert eng.classify(_event("match.card", card="red")).impact == Impact.CRITICAL
    assert eng.classify(_event("match.card", card="yellow")).impact == Impact.MEDIUM
    assert eng.classify(_event("match.substitution")).impact == Impact.MEDIUM
    assert eng.classify(_event("match.substitution", key_player=True)).impact == Impact.HIGH


# --- Part 4: Signal Engine -------------------------------------------------


def test_signal_engine_maps_categories() -> None:
    eng = EventImpactEngine()
    sig_eng = SignalEngine()
    cmid = uuid4()
    goal = sig_eng.generate(
        event=_event("match.goal"), classification=eng.classify(_event("match.goal")),
        canonical_match_id=cmid,
    )
    assert len(goal) == 1 and goal[0].signal_type == SignalType.GOAL
    assert goal[0].impact == "CRITICAL" and goal[0].confidence > 0
    # A routine fixture produces no signal.
    assert sig_eng.generate(
        event=_event("match.fixture"), classification=eng.classify(_event("match.fixture")),
        canonical_match_id=cmid,
    ) == []


# --- Part 5: Publication Engine --------------------------------------------


def test_publication_thresholds() -> None:
    eng = EventImpactEngine()
    sig_eng = SignalEngine()
    pub = PublicationEngine(min_confidence=0.7, min_impact=Impact.HIGH)
    cmid = uuid4()

    goal = sig_eng.generate(
        event=_event("match.goal"), classification=eng.classify(_event("match.goal")),
        canonical_match_id=cmid,
    )[0]
    assert pub.decide(goal).publish, "critical goal must publish"

    yellow_event = _event("match.card", card="yellow")
    yellow = sig_eng.generate(
        event=yellow_event, classification=eng.classify(yellow_event), canonical_match_id=cmid,
    )
    # A yellow card maps to no single-event signal type (not in the map),
    # so nothing to publish — verify the impact gate directly instead.
    sub = sig_eng.generate(
        event=_event("match.substitution"),
        classification=eng.classify(_event("match.substitution")),
        canonical_match_id=cmid,
    )[0]
    assert not pub.decide(sub).publish, "a MEDIUM lineup change must not publish"
    assert yellow == []


# --- Part 6: Event Aggregation ---------------------------------------------


async def test_aggregation_three_yellow_cards() -> None:
    eng = AggregationEngine(InMemoryAggregationStore())
    cmid = uuid4()
    s1 = await eng.observe(canonical_match_id=cmid, category="yellow_card")
    s2 = await eng.observe(canonical_match_id=cmid, category="yellow_card")
    assert s1 == [] and s2 == [], "below threshold → no aggregated signal"
    s3 = await eng.observe(canonical_match_id=cmid, category="yellow_card")
    assert len(s3) == 1
    assert s3[0].signal_type == SignalType.MOMENTUM_SWING
    assert s3[0].evidence_count == 3
    assert s3[0].metadata["aggregation"] == "aggressive_match"
    # Cooldown: a 4th card in the same window must not re-fire immediately.
    s4 = await eng.observe(canonical_match_id=cmid, category="yellow_card")
    assert s4 == []


# --- Part 3: Context Recalculation -----------------------------------------


def _ctx_engine() -> ContextRecalculationEngine:
    return ContextRecalculationEngine(
        checkpoint_tracker=CheckpointTracker(InMemoryCheckpointStore())
    )


async def test_context_triggers() -> None:
    eng = _ctx_engine()
    cmid = uuid4()
    crit = await eng.evaluate(canonical_match_id=cmid, impact=Impact.CRITICAL)
    assert crit.recalc and crit.trigger == "event"
    odds = await eng.evaluate(canonical_match_id=cmid, impact=Impact.LOW, odds_shift=True)
    assert odds.recalc and odds.trigger == "odds"
    # Time checkpoint fires once.
    t1 = await eng.evaluate(canonical_match_id=cmid, impact=Impact.LOW, minute=15)
    assert t1.recalc and t1.trigger == "time" and 15 in t1.checkpoints
    t2 = await eng.evaluate(canonical_match_id=cmid, impact=Impact.LOW, minute=20)
    assert not t2.recalc, "checkpoint 15 already fired; 30 not yet due"


def test_recompute_context_implied_probabilities() -> None:
    cmid = uuid4()
    odds_context = {"latest_odds": {"home": 2.0, "draw": 4.0, "away": 4.0}}
    ctx = recompute_context(canonical_match_id=cmid, minute=85, odds_context=odds_context)
    assert ctx["game_state"] == "late"
    probs = ctx["contextual_probabilities"]
    # 1/2 : 1/4 : 1/4 → normalised 0.5 : 0.25 : 0.25.
    assert probs["home"] == 0.5
    assert round(sum(probs.values()), 4) == 1.0
    assert ctx["pressure"] > 0


def test_recompute_carries_probabilities_forward() -> None:
    cmid = uuid4()
    prior = {"contextual_probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}, "momentum": 1.0}
    ctx = recompute_context(canonical_match_id=cmid, minute=75, odds_context=None, prior=prior)
    assert ctx["contextual_probabilities"]["home"] == 0.6
    assert ctx["momentum"] == 0.9  # decayed from 1.0


# --- Part 1: Identity (sqlite-backed registry) -----------------------------


@pytest.fixture
async def identity_resolver():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield IdentityResolver(IdentityRegistry(sf), tolerance_seconds=90 * 60)
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_identity_normalize_and_mint() -> None:
    assert normalize("Atlético-MG") == "atleticomg"
    k = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)
    assert mint(None, "brazil", "argentina", k) == mint(None, "brazil", "argentina", k)


async def test_identity_cross_provider_unifies(identity_resolver: IdentityResolver) -> None:
    comp = uuid4()
    k = datetime(2026, 6, 1, 19, 0, tzinfo=timezone.utc)
    a = await identity_resolver.resolve(
        ProviderMatchIdentity("api_football", "F1", comp, "Brazil", "Argentina", k)
    )
    b = await identity_resolver.resolve(
        ProviderMatchIdentity(
            "the_odds_api", "O9", comp, "Brazil", "Argentina",
            datetime(2026, 6, 1, 19, 20, tzinfo=timezone.utc),
        )
    )
    assert a == b, "same fixture across providers must unify within tolerance"


async def test_identity_resolve_from_event_prefers_stamp(
    identity_resolver: IdentityResolver,
) -> None:
    stamped = str(uuid4())
    event = {
        "event_id": str(uuid4()),
        "event_type": "match.odds",
        "competition_id": str(uuid4()),
        "match_id": str(uuid4()),
        "source": {"source_id": "the_odds_api", "confidence": 0.8},
        "payload": {
            "canonical_match_id": stamped,
            "external_event_id": "O9",
            "home_team": "Brazil",
            "away_team": "Argentina",
            "commence_time": "2026-06-01T19:00:00Z",
        },
    }
    got = await identity_resolver.resolve_from_event(event)
    assert str(got) == stamped


async def test_identity_fallback_to_match_id(identity_resolver: IdentityResolver) -> None:
    mid = str(uuid4())
    event = {
        "event_id": str(uuid4()),
        "event_type": "competition.standings",
        "match_id": mid,
        "source": {"source_id": "api_football"},
        "payload": {"rows": []},
    }
    got = await identity_resolver.resolve_from_event(event)
    assert str(got) == mid


# --- Composed pipeline -----------------------------------------------------


def _pipeline(identity_resolver: IdentityResolver) -> IntelligencePipeline:
    return IntelligencePipeline(
        identity_resolver=identity_resolver,
        impact_engine=EventImpactEngine(),
        signal_engine=SignalEngine(),
        aggregation_engine=AggregationEngine(InMemoryAggregationStore()),
        publication_engine=PublicationEngine(min_confidence=0.7, min_impact=Impact.HIGH),
        context_engine=_ctx_engine(),
        context_store=InMemoryMatchContextStore(),
    )


async def test_pipeline_goal_produces_published_signal_and_context(
    identity_resolver: IdentityResolver,
) -> None:
    pipe = _pipeline(identity_resolver)
    result = await pipe.process(_event("match.goal"), minute=70)
    assert result.classification.impact == Impact.CRITICAL
    assert any(s.signal_type == SignalType.GOAL for s in result.signals)
    assert result.recalc.recalc and result.recalc.trigger == "event"
    assert result.context is not None
    assert len(result.published) >= 1, "a critical goal signal must be published"


async def test_pipeline_routine_event_no_publication(
    identity_resolver: IdentityResolver,
) -> None:
    pipe = _pipeline(identity_resolver)
    result = await pipe.process(_event("match.fixture"))
    assert result.published == []
