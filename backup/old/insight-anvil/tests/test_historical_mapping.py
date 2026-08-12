"""The Explorer's envelopes → the historical ClickHouse tables.

These records are the five-year backfill Atlas needs a baseline from. The
tests below pin the two things that would make them useless without failing:
a NULL that became a 0, and a timestamp that became "now".
"""

from __future__ import annotations

import pytest

from anvil.clickhouse.schemas import (
    HISTORICAL_FIXTURES_COLUMNS,
    HISTORICAL_ODDS_COLUMNS,
    HISTORICAL_STATS_COLUMNS,
)
from anvil.mappers.historical import (
    HistoricalMappingError,
    map_fixture_row,
    map_odds_row,
    map_stats_row,
)


def envelope(entity_type: str, payload: dict, **overrides) -> dict:
    base = {
        "schema_version": "explorer.envelope.v1",
        "source": "football_data",
        "entity_type": entity_type,
        "external_id": "fd-2324-E0-0001",
        "trust_level": "high",
        "confidence": 0.92,
        "captured_at": "2026-08-07T12:00:00Z",
        "competition": {"competition_key": "premier_league"},
        "season": "2023-2024",
        "payload": payload,
    }
    base.update(overrides)
    return base


# --- column alignment ------------------------------------------------------

def test_every_row_matches_its_column_count():
    """A row one element short binds every following value to the wrong
    column — ClickHouse accepts it if the types happen to line up, and the
    table quietly fills with shifted data."""
    fixture = map_fixture_row(envelope("fixture", {
        "external_fixture_id": "fd-1", "scheduled_at": "2023-08-12T00:00:00Z",
        "status": "finished",
        "home_team": {"name": "Burnley"}, "away_team": {"name": "Man City"}}))
    assert len(fixture) == len(HISTORICAL_FIXTURES_COLUMNS)

    odds = map_odds_row(envelope("odds_snapshot", {
        "external_fixture_id": "fd-1", "bookmaker": "bet365", "market": "1x2",
        "captured_at": "2023-08-12T00:00:00Z",
        "selections": [{"name": "home", "price": 2.1}]}))
    assert len(odds) == len(HISTORICAL_ODDS_COLUMNS)

    stats = map_stats_row(envelope("stats", {
        "external_fixture_id": "fd-1", "home": {"shots": 10}, "away": {"shots": 18}}))
    assert len(stats) == len(HISTORICAL_STATS_COLUMNS)


# --- NULL is not zero ------------------------------------------------------

def test_an_unplayed_fixture_has_null_scores_not_zeros():
    """0-0 is a real result. A scheduled match has no result at all, and
    conflating them makes every future fixture look like a goalless draw."""
    row = map_fixture_row(envelope("fixture", {
        "external_fixture_id": "fd-1", "scheduled_at": "2026-08-12T00:00:00Z",
        "status": "scheduled",
        "home_team": {"name": "A"}, "away_team": {"name": "B"}}))
    columns = dict(zip(HISTORICAL_FIXTURES_COLUMNS, row))
    assert columns["home_score"] is None
    assert columns["away_score"] is None
    assert columns["status"] == "scheduled"


def test_missing_statistics_are_null_not_zero():
    """Older seasons omit the stat columns. Zero shots is a real (if
    unusual) match; "not recorded" is not, and a query for low-shot matches
    would otherwise return every old season."""
    row = map_stats_row(envelope("stats", {
        "external_fixture_id": "fd-1",
        "home": {"shots": 10}, "away": {"shots": 18}}))
    columns = dict(zip(HISTORICAL_STATS_COLUMNS, row))
    assert columns["home_shots"] == 10
    assert columns["home_corners"] is None
    assert columns["home_possession"] is None


def test_a_partial_bookmaker_quote_keeps_the_missing_leg_null():
    row = map_odds_row(envelope("odds_snapshot", {
        "external_fixture_id": "fd-1", "bookmaker": "bet365", "market": "1x2",
        "captured_at": "2023-08-12T00:00:00Z",
        "selections": [{"name": "home", "price": 2.1}, {"name": "away", "price": 3.6}]}))
    columns = dict(zip(HISTORICAL_ODDS_COLUMNS, row))
    assert columns["home_price"] == "2.1"
    assert columns["away_price"] == "3.6"
    # A missing leg as 0 would read as a price, and a 0 price is an
    # arbitrage that does not exist.
    assert columns["draw_price"] is None


# --- time ------------------------------------------------------------------

def test_odds_keep_the_market_timestamp_not_the_download_time():
    """Closing odds are published after the fact. The envelope's captured_at
    is when we fetched the CSV; the payload's is when the market said it.
    Using the former puts a 2023 market in 2026 and makes any analysis of
    line movement meaningless."""
    row = map_odds_row(envelope("odds_snapshot", {
        "external_fixture_id": "fd-1", "bookmaker": "bet365", "market": "1x2",
        "captured_at": "2023-08-12T00:00:00Z",
        "selections": [{"name": "home", "price": 2.1}]}))
    columns = dict(zip(HISTORICAL_ODDS_COLUMNS, row))
    assert columns["captured_at"] == "2023-08-12T00:00:00Z"


# --- decimals --------------------------------------------------------------

def test_prices_never_pass_through_float_formatting():
    """Decimals reach ClickHouse as strings. Going through a float first
    turns 2.10 into 2.0999999 in a column meant for a price."""
    row = map_odds_row(envelope("odds_snapshot", {
        "external_fixture_id": "fd-1", "bookmaker": "pinnacle", "market": "1x2",
        "captured_at": "2023-08-12T00:00:00Z",
        "selections": [{"name": "home", "price": "10.25"}]}))
    columns = dict(zip(HISTORICAL_ODDS_COLUMNS, row))
    assert isinstance(columns["home_price"], str)
    assert columns["home_price"] == "10.25"


# --- identity --------------------------------------------------------------

def test_match_id_stays_null_until_entity_resolution():
    """Minting a UUID here would create an identity nothing else can
    reproduce, and the join to live matches would silently never match."""
    row = map_fixture_row(envelope("fixture", {
        "external_fixture_id": "fd-1", "scheduled_at": "2023-08-12T00:00:00Z",
        "home_team": {"name": "A"}, "away_team": {"name": "B"}}))
    columns = dict(zip(HISTORICAL_FIXTURES_COLUMNS, row))
    assert columns["match_id"] is None
    assert columns["external_fixture_id"] == "fd-1"


def test_an_envelope_without_competition_or_season_is_refused():
    """They are the partition key. A row with empty ones lands in a
    partition no query for a real competition will ever scan — present in
    the table and invisible."""
    with pytest.raises(HistoricalMappingError):
        map_fixture_row(envelope("fixture", {
            "external_fixture_id": "fd-1", "scheduled_at": "2023-08-12T00:00:00Z",
            "home_team": {"name": "A"}, "away_team": {"name": "B"}},
            competition={}, season=""))


def test_provenance_is_carried_through_not_recomputed():
    """Confidence and trust are what let a consumer weigh two sources that
    disagree. A number invented here would be one nothing produced."""
    row = map_fixture_row(envelope("fixture", {
        "external_fixture_id": "fd-1", "scheduled_at": "2023-08-12T00:00:00Z",
        "home_team": {"name": "A"}, "away_team": {"name": "B"}},
        trust_level="medium", confidence=0.7))
    columns = dict(zip(HISTORICAL_FIXTURES_COLUMNS, row))
    assert columns["trust_level"] == "medium"
    assert columns["confidence"] == "0.7"


def test_odds_with_no_usable_price_are_refused():
    with pytest.raises(HistoricalMappingError):
        map_odds_row(envelope("odds_snapshot", {
            "external_fixture_id": "fd-1", "bookmaker": "x", "market": "1x2",
            "selections": []}))
