"""TrendEngine cooldown: subject discrimination + fail-open.

Two Round-4 fixes, neither previously covered:

1. The cooldown key was `trend:{match}:{trend_type}`. Detectors that
   legitimately emit SEVERAL trends of the same type in one tick
   (MarketAnomalyDetector — one per outlier bookmaker; MetaTrendDetector
   — one per team) had all but the first silently dropped into
   `trends_suppressed_total`, with no record of which subject was lost.

2. `allow_fire` (Redis in production) sat outside any try, so a
   transient Redis failure propagated out of `detect()` — whose
   docstring promises "Never raises" — and killed the whole pipeline
   tick, discarding trends that had already been detected.
"""

from __future__ import annotations

from uuid import uuid4

from atlas.event_aggregation import InMemoryAggregationStore
from atlas.trends.engine import TrendEngine, _cooldown_key
from atlas.trends.models import Trend, TrendCategory, TrendInputs, TrendType


def _trend(*, evidence=None, trend_type=TrendType.market_anomaly, match_id=None):
    return Trend(
        trend_type=trend_type,
        category=TrendCategory.ninja,
        canonical_match_id=match_id or uuid4(),
        confidence=0.8,
        strength=0.7,
        evidence=evidence or {},
    )


class _StaticDetector:
    """Emits a fixed trend list, mimicking a multi-emission detector."""

    def __init__(self, trends):
        self._trends = trends

    def detect(self, inputs):
        return self._trends


class _BrokenCooldown:
    async def allow_fire(self, key, now, ttl):
        raise ConnectionError("redis unreachable")


# --- key construction -------------------------------------------------------


def test_cooldown_key_includes_bookmaker_subject():
    mid = uuid4()
    a = _cooldown_key(_trend(match_id=mid, evidence={"bookmaker": "bet365"}))
    b = _cooldown_key(_trend(match_id=mid, evidence={"bookmaker": "pinnacle"}))
    assert a != b, "distinct bookmakers must not share a cooldown slot"


def test_cooldown_key_includes_team_subject():
    mid = uuid4()
    a = _cooldown_key(_trend(match_id=mid, evidence={"team": "arsenal"}))
    b = _cooldown_key(_trend(match_id=mid, evidence={"team": "chelsea"}))
    assert a != b


def test_cooldown_key_without_subject_is_unchanged():
    mid = uuid4()
    t = _trend(match_id=mid, evidence={"deviation": 0.1})
    assert _cooldown_key(t) == f"trend:{mid}:{TrendType.market_anomaly.value}"


def test_cooldown_key_is_deterministic():
    mid = uuid4()
    t = _trend(match_id=mid, evidence={"bookmaker": "bet365", "team": "arsenal"})
    assert _cooldown_key(t) == _cooldown_key(t)


# --- behaviour through the engine -------------------------------------------


async def test_multi_emission_same_type_all_survive_cooldown():
    """The actual regression: 3 outlier bookmakers in one tick must
    produce 3 trends, not 1."""
    mid = uuid4()
    trends = [
        _trend(match_id=mid, evidence={"bookmaker": book})
        for book in ("bet365", "pinnacle", "william_hill")
    ]
    engine = TrendEngine(
        detectors=[_StaticDetector(trends)],
        cooldown_store=InMemoryAggregationStore(),
    )

    kept = await engine.detect(TrendInputs(canonical_match_id=mid))

    assert len(kept) == 3
    assert {t.evidence["bookmaker"] for t in kept} == {
        "bet365", "pinnacle", "william_hill"
    }


async def test_same_subject_still_suppressed_on_repeat():
    """Cooldown must still do its actual job for the same subject."""
    mid = uuid4()
    store = InMemoryAggregationStore()
    trend = _trend(match_id=mid, evidence={"bookmaker": "bet365"})
    engine = TrendEngine(detectors=[_StaticDetector([trend])], cooldown_store=store)

    first = await engine.detect(TrendInputs(canonical_match_id=mid))
    second = await engine.detect(TrendInputs(canonical_match_id=mid))

    assert len(first) == 1
    assert len(second) == 0  # suppressed, as intended


async def test_cooldown_failure_fails_open_and_never_raises():
    """detect() promises 'Never raises'. A Redis outage must not kill
    the tick — the trend goes through instead."""
    mid = uuid4()
    trend = _trend(match_id=mid)
    engine = TrendEngine(
        detectors=[_StaticDetector([trend])], cooldown_store=_BrokenCooldown()
    )

    kept = await engine.detect(TrendInputs(canonical_match_id=mid))

    assert len(kept) == 1, "fail-open: a cooldown outage must not drop the trend"
