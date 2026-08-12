"""market_features.py coverage — thin adapter over the existing
atlas/market/ engines, exercised with synthetic OddsTick histories."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from atlas.odds.models import OddsTick
from atlas.strength.market_features import market_features_for_match


def _tick(*, home, draw, away, bookmaker="bet365", captured_at, match_id=None):
    return OddsTick(
        canonical_event_id=uuid4(),
        provider="the_odds_api",
        competition_id=uuid4(),
        match_id=match_id or uuid4(),
        market="h2h",
        bookmaker=bookmaker,
        home=home, draw=draw, away=away,
        captured_at=captured_at,
    )


def test_no_history_is_unavailable():
    features = market_features_for_match([])
    assert features.market_available is False
    assert features.market_pressure is None
    assert features.market_entropy is None
    assert features.line_movement is None


def test_single_snapshot_available_but_no_line_movement():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = [_tick(home=1.80, draw=3.40, away=4.50, captured_at=now)]
    features = market_features_for_match(history)
    assert features.market_available is True
    assert features.market_pressure is not None
    assert features.market_entropy is not None
    assert features.line_movement is None  # only one snapshot, no open/close pair


def test_market_pressure_reflects_strong_favorite():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # A heavy home favorite (1.10) should show high market_pressure and
    # low entropy (the market is decisive).
    strong_fav = market_features_for_match(
        [_tick(home=1.10, draw=8.0, away=15.0, captured_at=now)]
    )
    # An even 3-way market should show low market_pressure and high entropy.
    even = market_features_for_match(
        [_tick(home=3.0, draw=3.0, away=3.0, captured_at=now)]
    )
    assert strong_fav.market_pressure > even.market_pressure
    assert strong_fav.market_entropy < even.market_entropy


def test_line_movement_across_two_snapshots():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=6)
    # Opens even, closes as a home favorite -> positive line_movement.
    history = [
        _tick(home=3.0, draw=3.0, away=3.0, captured_at=t0),
        _tick(home=1.50, draw=4.0, away=6.0, captured_at=t1),
    ]
    features = market_features_for_match(history)
    assert features.line_movement is not None
    assert features.line_movement > 0


def test_line_movement_bounded():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=6)
    history = [
        _tick(home=1.01, draw=50.0, away=50.0, captured_at=t0),
        _tick(home=50.0, draw=50.0, away=1.01, captured_at=t1),
    ]
    features = market_features_for_match(history)
    assert -1.0 <= features.line_movement <= 1.0
