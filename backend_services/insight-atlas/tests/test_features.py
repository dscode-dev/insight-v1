from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from atlas.features.builders import (
    build_late_pressure,
    build_market,
    build_momentum,
    build_pressure,
    build_sentiment,
    build_signal_density,
)
from atlas.features.definitions import FEATURE_NAMES, registry
from atlas.features.pipeline import build_snapshot
from atlas.features.snapshot import FeatureSnapshot


class StubAnalytics:
    def __init__(self, *, ph=0.7, pa=0.45, std=0.12, shift=-0.04, count=14, series=None, minute=70):
        self.ph = ph
        self.pa = pa
        self.std = std
        self.shift = shift
        self.count = count
        self.series = series or [(0.5, 0.5), (0.55, 0.45), (0.7, 0.3)]
        self.minute = minute

    async def pressure_means(self, *, match_id, as_of, window_seconds):
        return (self.ph, self.pa)

    async def consensus_movement(self, *, match_id, as_of, window_seconds):
        return (self.std, self.shift)

    async def signal_count(self, *, match_id, as_of, window_seconds):
        return self.count

    async def pressure_series(self, *, match_id, as_of, limit):
        return self.series[:limit]

    async def match_minute(self, *, match_id, as_of):
        return self.minute


class StubSentiment:
    def __init__(self, *, latest=0.65, prior=0.5):
        self.latest = latest
        self.prior = prior

    async def latest_value(self, match_id):
        return self.latest

    async def value_5m_ago(self, match_id, as_of):
        return self.prior


def test_definitions_are_complete() -> None:
    assert set(registry.keys()) == set(FEATURE_NAMES)
    # Every feature has a non-degenerate envelope.
    for name in FEATURE_NAMES:
        fd = registry[name]
        assert fd.low <= fd.default <= fd.high


async def test_build_pressure_returns_delta() -> None:
    analytics = StubAnalytics(ph=0.7, pa=0.45)
    out = await build_pressure(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["pressure_home_5m"] == 0.7
    assert out["pressure_away_5m"] == 0.45
    assert abs(out["pressure_delta"] - 0.25) < 1e-9


async def test_build_market_clamps_stability() -> None:
    analytics = StubAnalytics(std=0.5)
    out = await build_market(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["market_volatility"] == 0.5
    assert 0.0 <= out["market_stability_score"] <= 1.0


async def test_build_signal_density_normalises_per_minute() -> None:
    analytics = StubAnalytics(count=20)
    out = await build_signal_density(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["signal_density"] == 2.0  # 20 over 10min


async def test_build_momentum_uses_endpoints_of_series() -> None:
    analytics = StubAnalytics(
        series=[(0.3, 0.6), (0.4, 0.5), (0.7, 0.3)]
    )  # net: -0.3, -0.1, +0.4
    out = await build_momentum(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["momentum_score"] == pytest.approx(0.7)


async def test_late_pressure_zero_before_minute_60() -> None:
    analytics = StubAnalytics(minute=30)
    out = await build_late_pressure(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["late_pressure_score"] == registry["late_pressure_score"].default


async def test_late_pressure_active_past_minute_60() -> None:
    analytics = StubAnalytics(minute=75, ph=0.6, pa=0.4)
    out = await build_late_pressure(
        analytics, match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["late_pressure_score"] == pytest.approx(0.5)


async def test_sentiment_delta_is_diff() -> None:
    sentiment = StubSentiment(latest=0.6, prior=0.4)
    out = await build_sentiment(sentiment, match_id=uuid4(), as_of=datetime.now(timezone.utc))
    assert out["community_confidence"] == pytest.approx(0.6)
    # With both latest and prior present the builder yields the difference.
    assert out["sentiment_delta"] == pytest.approx(0.2)


async def test_sentiment_delta_defaults_when_prior_missing() -> None:
    """When the reader has no history, the prior is None and the
    delta falls back to the registry default."""

    class StubNoPrior:
        async def latest_value(self, match_id):
            return 0.6

        async def value_5m_ago(self, match_id, as_of):
            return None

    out = await build_sentiment(
        StubNoPrior(), match_id=uuid4(), as_of=datetime.now(timezone.utc)
    )
    assert out["sentiment_delta"] == pytest.approx(registry["sentiment_delta"].default)


async def test_full_pipeline_produces_dense_snapshot() -> None:
    snap = await build_snapshot(
        match_id=uuid4(),
        competition_id=None,
        as_of=datetime.now(timezone.utc),
        schema_version=1,
        analytics=StubAnalytics(),
        sentiment=StubSentiment(),
    )
    assert isinstance(snap, FeatureSnapshot)
    # Every feature is present after with_defaults().
    assert set(snap.features.keys()) == set(FEATURE_NAMES)
    # Vector has the right length and order.
    vec = snap.to_vector()
    assert len(vec) == len(FEATURE_NAMES)
