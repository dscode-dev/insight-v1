"""Odds pipeline coverage — parsing, persistence (full history),
foundational features, descriptive context, and the match.odds
consumer-validation extension.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import fakeredis.aioredis
import pytest

from atlas.odds import (
    OddsContextStore,
    OddsFeatureStore,
    OddsHandler,
    OddsRepository,
    build_odds_context,
    build_odds_features,
    parse_odds_event,
)
from atlas.odds.models import OddsParseError, OddsTick
from atlas.registry import build_engine, build_session_factory
from atlas.registry.base import Base
import atlas.registry.models  # noqa: F401
from atlas.streaming.canonical_consumer import (
    CanonicalEnvelope,
    MalformedEnvelopeError,
)


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
async def odds_repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    url = f"sqlite+aiosqlite:///{path}"
    # SQLite doesn't understand the `atlas` schema clause from the ORM.
    for tbl in Base.metadata.tables.values():
        tbl.schema = None
    engine = build_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sf = build_session_factory(engine)
    try:
        yield OddsRepository(sf)
    finally:
        await engine.dispose()
        try:
            os.unlink(path)
        except OSError:
            pass


def _odds_event(
    *,
    match_id: str,
    bookmaker: str = "bet365",
    market: str = "h2h",
    home: float = 1.83,
    draw: float = 3.40,
    away: float = 4.75,
    captured_at: str = "2026-06-01T10:00:00Z",
    event_id: str | None = None,
) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "schema_version": "v1",
        "event_type": "match.odds",
        "occurred_at": captured_at,
        "match_id": str(uuid4()),  # snapshot-scoped — ignored for grouping
        "competition_id": str(uuid4()),
        "payload": {
            "provider": "the_odds_api",
            "competition_id": str(uuid4()),
            "match_id": match_id,
            "market": market,
            "bookmaker": bookmaker,
            "home": home,
            "draw": draw,
            "away": away,
            "captured_at": captured_at,
        },
        "source": {"source_id": "the_odds_api"},
        "lineage": [{"source_id": "the_odds_api"}],
        "status": "candidate",
    }


def _tick(**kw) -> OddsTick:
    base = dict(
        canonical_event_id=uuid4(),
        provider="the_odds_api",
        competition_id=uuid4(),
        match_id=uuid4(),
        market="h2h",
        bookmaker="bet365",
        home=1.83,
        draw=3.40,
        away=4.75,
        captured_at=datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        payload={},
    )
    base.update(kw)
    return OddsTick(**base)


# --- parsing ----------------------------------------------------------------


def test_parse_odds_event_happy() -> None:
    mid = str(uuid4())
    tick = parse_odds_event(_odds_event(match_id=mid))
    assert str(tick.match_id) == mid
    assert tick.market == "h2h"
    assert tick.bookmaker == "bet365"
    assert tick.home == 1.83
    assert tick.captured_at.tzinfo is not None


def test_parse_odds_event_missing_market() -> None:
    ev = _odds_event(match_id=str(uuid4()))
    del ev["payload"]["market"]
    with pytest.raises(OddsParseError):
        parse_odds_event(ev)


# --- features ---------------------------------------------------------------


def test_build_odds_features_empty() -> None:
    f = build_odds_features([])
    assert f["home_odds"] == 0.0
    assert f["bookmaker_count"] == 0.0


def test_build_odds_features_consensus_and_movement() -> None:
    mid = uuid4()
    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    history = [
        _tick(match_id=mid, bookmaker="bet365", home=1.85, captured_at=t0),
        _tick(match_id=mid, bookmaker="pinnacle", home=1.83, captured_at=t0),
        # later snapshot — home drifts up
        _tick(
            match_id=mid,
            bookmaker="bet365",
            home=1.95,
            captured_at=t0 + timedelta(minutes=5),
        ),
    ]
    f = build_odds_features(history)
    assert f["bookmaker_count"] == 2.0
    assert f["market_count"] == 1.0
    # latest consensus = mean(latest bet365=1.95, latest pinnacle=1.83)
    assert round(f["home_odds"], 3) == round((1.95 + 1.83) / 2, 3)
    assert f["odds_movement"] == 1.0
    assert f["odds_delta"] > 0


# --- context ----------------------------------------------------------------


def test_build_odds_context_consensus() -> None:
    mid = uuid4()
    history = [
        _tick(match_id=mid, bookmaker="bet365", home=1.85, draw=3.4, away=4.7),
        _tick(match_id=mid, bookmaker="pinnacle", home=1.83, draw=3.5, away=4.9),
    ]
    ctx = build_odds_context(mid, history)
    assert ctx["match_id"] == str(mid)
    assert ctx["bookmaker_count"] == 2
    assert "h2h" in ctx["market_state"]
    assert len(ctx["market_state"]["h2h"]) == 2
    assert round(ctx["latest_odds"]["home"], 3) == round((1.85 + 1.83) / 2, 3)


# --- persistence: full history + idempotency --------------------------------


async def test_repository_preserves_full_history(odds_repo: OddsRepository) -> None:
    mid = uuid4()
    times = [
        datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 10, 2, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 10, 5, tzinfo=timezone.utc),
    ]
    prices = [1.85, 1.82, 1.88]
    for ts, price in zip(times, prices):
        assert await odds_repo.record(
            _tick(match_id=mid, home=price, captured_at=ts)
        )

    history = await odds_repo.history(mid)
    assert len(history) == 3
    # Stored oldest→newest; every snapshot preserved (NOT just latest).
    assert [t.home for t in history] == prices


async def test_repository_idempotent_on_event_id(odds_repo: OddsRepository) -> None:
    mid = uuid4()
    eid = uuid4()
    first = await odds_repo.record(_tick(canonical_event_id=eid, match_id=mid))
    second = await odds_repo.record(_tick(canonical_event_id=eid, match_id=mid))
    assert first is True
    assert second is False
    assert await odds_repo.count_for_match(mid) == 1


# --- handler integration ----------------------------------------------------


async def test_handler_persists_and_builds_views(odds_repo: OddsRepository) -> None:
    redis = fakeredis.aioredis.FakeRedis()
    handler = OddsHandler(
        repository=odds_repo,
        feature_store=OddsFeatureStore(
            redis=redis, key_prefix="atlas:odds:", ttl_seconds=60
        ),
        context_store=OddsContextStore(
            redis=redis, key_prefix="atlas:odds:", ttl_seconds=60
        ),
    )
    mid = str(uuid4())
    for price, ts in [
        (1.85, "2026-06-01T10:00:00Z"),
        (1.90, "2026-06-01T10:05:00Z"),
    ]:
        ev = _odds_event(match_id=mid, home=price, captured_at=ts)
        env = CanonicalEnvelope.from_payload(_wire(ev))
        await handler.handle(env)

    from uuid import UUID

    history = await odds_repo.history(UUID(mid))
    assert len(history) == 2
    ctx = await handler.context_for(UUID(mid))
    assert ctx is not None
    assert ctx["snapshot_count"] == 2
    await redis.aclose()


# --- consumer validation extension ------------------------------------------


def _wire(event: dict) -> bytes:
    import json

    return json.dumps(
        {
            "schema_version": "v1",
            "stream": "odds",
            "idempotency_key": f"{event['event_id']}::{event.get('status', 'candidate')}",
            "event": event,
            "published_at": "2026-06-01T10:00:00Z",
        }
    ).encode("utf-8")


def test_consumer_accepts_match_odds() -> None:
    env = CanonicalEnvelope.from_payload(_wire(_odds_event(match_id=str(uuid4()))))
    assert env.event["event_type"] == "match.odds"
    assert env.stream == "odds"


def test_consumer_rejects_match_odds_without_market() -> None:
    ev = _odds_event(match_id=str(uuid4()))
    del ev["payload"]["market"]
    with pytest.raises(MalformedEnvelopeError):
        CanonicalEnvelope.from_payload(_wire(ev))


# --- outcomes audit (non-h2h markets) ---------------------------------------


def _totals_event(*, match_id: str, line: float = 2.5, over: float = 1.9) -> dict:
    """A non-h2h (over_under) event: no home/draw/away, only outcomes[]."""
    return {
        "event_id": str(uuid4()),
        "schema_version": "v1",
        "event_type": "match.odds",
        "occurred_at": "2026-06-01T10:00:00Z",
        "match_id": str(uuid4()),
        "competition_id": str(uuid4()),
        "payload": {
            "provider": "the_odds_api",
            "match_id": match_id,
            "market": "totals",
            "bookmaker": "pinnacle",
            "captured_at": "2026-06-01T10:00:00Z",
            "outcomes": [
                {"name": "Over", "price": over, "point": line},
                {"name": "Under", "price": 1.9, "point": line},
            ],
        },
        "source": {"source_id": "the_odds_api"},
        "lineage": [{"source_id": "the_odds_api"}],
        "status": "candidate",
    }


def test_parse_non_h2h_has_outcomes_but_no_h2h_fields() -> None:
    tick = parse_odds_event(_totals_event(match_id=str(uuid4())))
    assert tick.market == "totals"
    assert tick.home is None and tick.draw is None and tick.away is None
    outs = tick.outcomes()
    assert len(outs) == 2
    assert outs[0]["point"] == 2.5  # the line is preserved


async def test_non_h2h_outcomes_persist_and_propagate(odds_repo: OddsRepository) -> None:
    from uuid import UUID

    redis = fakeredis.aioredis.FakeRedis()
    handler = OddsHandler(
        repository=odds_repo,
        feature_store=OddsFeatureStore(redis=redis, key_prefix="atlas:odds:", ttl_seconds=60),
        context_store=OddsContextStore(redis=redis, key_prefix="atlas:odds:", ttl_seconds=60),
    )
    mid = str(uuid4())
    env = CanonicalEnvelope.from_payload(_wire(_totals_event(match_id=mid)))
    await handler.handle(env)

    # Persisted with full payload (outcomes survive the round-trip).
    history = await odds_repo.history(UUID(mid))
    assert len(history) == 1
    assert len(history[0].outcomes()) == 2

    # Context propagates outcomes for the non-h2h market.
    ctx = await handler.context_for(UUID(mid))
    assert "totals" in ctx["market_state"]
    entry = ctx["market_state"]["totals"][0]
    assert entry["home"] is None
    assert len(entry["outcomes"]) == 2
    assert entry["outcomes"][0]["point"] == 2.5
    await redis.aclose()
