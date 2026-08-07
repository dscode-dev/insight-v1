"""The sources added for the historical backfill, and the entity types that
made them possible.

No network: every test feeds the normalizer an artifact shaped exactly like
the one its adapter builds, and checks the envelope that comes out against the
real contract. What the adapters produce from the live sources was verified
separately, from the collecting host — reachability is a property of the
network, not of this code, and a test that asserted it would fail for reasons
nobody here can fix.
"""

from __future__ import annotations

import pytest

from explorer.adapters.base import RawArtifact
from explorer.adapters.football_data import _odds_rows, _stats_payload
from explorer.adapters.openfootball import _season_dir
from explorer.normalizers.espn import NormalizationError
from explorer.normalizers.registry import normalize_artifact
from explorer.pipelines.catalog import COLLECTIBLE_THEMES
from explorer.sources import build_default_registry
from explorer.validators.schema import validate_envelope


def _artifact(source: str, entity_type: str, raw: dict, **kw) -> RawArtifact:
    return RawArtifact(
        source=source, provider=f"{source}-test", entity_type=entity_type,
        external_id=kw.get("external_id", "x-1"),
        competition_key=kw.get("competition_key", "premier_league"),
        season=kw.get("season", "2023-2024"),
        url="https://example.test/x", method="file",
        retrieved_at="2026-08-07T00:00:00Z", raw=raw,
        trust_level="high", source_type="historical",
    )


# --- the entity_type unlock ------------------------------------------------

def test_envelope_carries_the_entity_type_it_was_given():
    """The whole reason odds and stats were uncollectible.

    `build_envelope` hardcoded "fixture", so an odds payload was validated
    against the fixture schema and rejected — one layer below where anyone
    debugging a rejected odds record would have looked.
    """
    row = {"_fixture_id": "fd-1", "_date": "12/08/2023", "bookmaker": "bet365",
           "market": "1x2", "selections": [{"name": "home", "price": 2.1},
                                           {"name": "draw", "price": 3.4},
                                           {"name": "away", "price": 3.6}]}
    env = normalize_artifact(_artifact("football_data", "odds_snapshot", row))
    assert env["entity_type"] == "odds_snapshot"
    assert validate_envelope(env) == []


def test_odds_and_stats_are_collectible_themes():
    assert {"fixtures", "odds", "stats"} <= COLLECTIBLE_THEMES
    # Contracts exist for these and nothing produces them. Declaring them
    # would have the scheduler plan tasks that can only come back empty.
    assert "lineups" not in COLLECTIBLE_THEMES
    assert "injuries" not in COLLECTIBLE_THEMES


# --- football_data: three entity types from one CSV row --------------------

_FD_ROW = {
    "Date": "12/08/2023", "HomeTeam": "Burnley", "AwayTeam": "Man City",
    "FTHG": "0", "FTAG": "3", "FTR": "A", "HTHG": "0", "HTAG": "2",
    "HS": "10", "AS": "18", "HST": "3", "AST": "7", "HC": "4", "AC": "6",
    "HF": "11", "AF": "9", "HY": "2", "AY": "1", "HR": "0", "AR": "0",
    "B365H": "9.5", "B365D": "5.75", "B365A": "1.33",
    "PSH": "10.2", "PSD": "5.9", "PSA": "1.32",
}


def test_football_data_row_yields_stats_matching_the_contract():
    stats = _stats_payload(_FD_ROW)
    assert stats is not None
    assert stats["home"]["shots"] == 10
    assert stats["away"]["shots_on_target"] == 7
    env = normalize_artifact(
        _artifact("football_data", "stats", {"_fixture_id": "fd-1", **stats}))
    assert validate_envelope(env) == []


def test_football_data_row_yields_one_odds_snapshot_per_bookmaker():
    rows = list(_odds_rows(_FD_ROW))
    assert {r["bookmaker"] for r in rows} == {"bet365", "pinnacle"}
    for row in rows:
        assert [s["name"] for s in row["selections"]] == ["home", "draw", "away"]


def test_partial_bookmaker_quotes_are_skipped():
    """A market missing an outcome is not a market.

    Filling the gap with null would be indistinguishable downstream from a
    price of zero, and a zero price is an arbitrage that does not exist.
    """
    partial = {**_FD_ROW, "PSD": "", "PSA": ""}
    assert {r["bookmaker"] for r in _odds_rows(partial)} == {"bet365"}


def test_odds_below_evens_are_rejected_as_parse_artefacts():
    """A decimal odd of 1.0 or less pays no more than the stake.

    Empty CSV cells read as 0.0, which the contract would reject anyway —
    catching it here keeps a whole season from failing validation on cells
    that were simply blank.
    """
    impossible = {**_FD_ROW, "B365H": "0", "B365D": "0", "B365A": "0"}
    assert {r["bookmaker"] for r in _odds_rows(impossible)} == {"pinnacle"}


def test_rows_without_statistics_produce_no_stats_artifact():
    """Older seasons omit the stat columns. An artifact with every field
    empty would count as a collected record and inflate coverage."""
    bare = {"Date": "12/08/2023", "HomeTeam": "A", "AwayTeam": "B",
            "FTHG": "1", "FTAG": "0"}
    assert _stats_payload(bare) is None


def test_odds_are_stamped_with_the_match_date_not_the_download_time():
    """These are closing odds published after the fact. Stamping them with
    the download time would place a 2023 market in 2026 and make any
    time-ordered analysis of line movement meaningless."""
    env = normalize_artifact(_artifact("football_data", "odds_snapshot", {
        "_fixture_id": "fd-1", "_date": "12/08/2023", "bookmaker": "bet365",
        "market": "1x2", "selections": [{"name": "home", "price": 2.0}]}))
    assert env["payload"]["captured_at"].startswith("2023-08-12")


# --- openfootball ----------------------------------------------------------

def test_openfootball_season_directory_conversion():
    assert _season_dir("2023-2024") == "2023-24"
    assert _season_dir("2023-24") == "2023-24"


def test_openfootball_refuses_a_single_year_season():
    """European seasons span two calendar years. Picking 2023-24 over
    2022-23 for the label '2023' would silently fetch a different season
    under the label the operator asked for."""
    assert _season_dir("2023") is None


def test_openfootball_finished_and_scheduled_match():
    played = normalize_artifact(_artifact("openfootball", "fixture", {
        "date": "2023-08-11", "time": "20:00", "team1": "Burnley FC",
        "team2": "Manchester City FC", "score": {"ft": [0, 3], "ht": [0, 2]}},
        competition_key="premier_league"))
    assert played["payload"]["status"] == "finished"
    assert played["payload"]["score"] == {"home": 0, "away": 3,
                                          "halftime_home": 0, "halftime_away": 2}
    assert validate_envelope(played) == []

    # No `score` key at all is how football.json marks an unplayed fixture —
    # that is what separates a scheduled match from a real 0-0.
    upcoming = normalize_artifact(_artifact("openfootball", "fixture", {
        "date": "2026-08-11", "team1": "A FC", "team2": "B FC"}))
    assert upcoming["payload"]["status"] == "scheduled"
    assert "score" not in upcoming["payload"]
    assert validate_envelope(upcoming) == []


# --- statsbomb -------------------------------------------------------------

def test_statsbomb_match_normalises_and_validates():
    env = normalize_artifact(_artifact("statsbomb", "fixture", {
        "match_id": 3754058, "match_date": "2015-09-19", "kick_off": "17:30:00.000",
        "home_team": {"home_team_id": 1, "home_team_name": "Chelsea"},
        "away_team": {"away_team_id": 2, "away_team_name": "Arsenal"},
        "home_score": 2, "away_score": 0, "match_status": "available",
        "competition_stage": {"name": "Regular Season"}},
        external_id="sb-3754058"))
    assert env["payload"]["status"] == "finished"
    assert env["payload"]["home_team"]["external_id"] == "1"
    # Millisecond precision is dropped; nothing downstream reads below the second.
    assert env["payload"]["scheduled_at"] == "2015-09-19T17:30:00Z"
    assert validate_envelope(env) == []


# --- api_football ----------------------------------------------------------

def test_api_football_finished_status_survives_an_unknown_code():
    """A status the map does not know must not be filed as `scheduled` when
    a score exists — a finished match filed that way is invisible to anything
    reading results."""
    env = normalize_artifact(_artifact("api_football", "fixture", {
        "fixture": {"id": 1, "date": "2023-08-11T19:00:00+00:00",
                    "status": {"short": "SOMETHING_NEW", "long": "?"}},
        "teams": {"home": {"id": 33, "name": "Burnley"},
                  "away": {"id": 50, "name": "Manchester City"}},
        "goals": {"home": 0, "away": 3},
        "score": {"halftime": {"home": 0, "away": 2}}},
        external_id="af-1"))
    assert env["payload"]["status"] == "finished"
    assert validate_envelope(env) == []


# --- odds_api --------------------------------------------------------------

def test_odds_api_translates_team_names_into_market_positions():
    """The API names outcomes by team. Keeping the team name would give every
    fixture its own market vocabulary, which nothing can aggregate."""
    env = normalize_artifact(_artifact("odds_api", "odds_snapshot", {
        "_event": {"id": "abc", "home_team": "Arsenal", "away_team": "Chelsea"},
        "bookmaker": "pinnacle", "market": "h2h",
        "last_update": "2026-08-07T00:00:00Z",
        "outcomes": [{"name": "Arsenal", "price": 1.8},
                     {"name": "Chelsea", "price": 4.2},
                     {"name": "Draw", "price": 3.5}]},
        external_id="oa-abc"))
    assert {s["name"] for s in env["payload"]["selections"]} == {"home", "away", "draw"}
    # h2h is this API's name for 1X2; translated so odds from here and from
    # Football-Data land under one market key.
    assert env["payload"]["market"] == "1x2"
    assert validate_envelope(env) == []


def test_odds_api_market_with_no_usable_price_is_refused():
    with pytest.raises(NormalizationError):
        normalize_artifact(_artifact("odds_api", "odds_snapshot", {
            "_event": {"id": "abc", "home_team": "A", "away_team": "B"},
            "bookmaker": "x", "market": "h2h",
            "outcomes": [{"name": "A", "price": 1.0}]}))


# --- registry --------------------------------------------------------------

def test_every_registered_source_has_a_normalizer():
    """A source with no normalizer collects into the raw layer and then
    rejects everything at normalization — visible only as a mysterious 100%
    reject rate on one source."""
    from explorer.normalizers.registry import _NORMALIZERS

    missing = [a.name for a in build_default_registry()
               if a.name not in _NORMALIZERS and a.name != "wikipedia"]
    assert missing == [], f"sources without a normalizer: {missing}"


def test_keyed_sources_are_offline_without_a_key(monkeypatch):
    """Registered, holding a credential and switched on are three different
    things. Without a key these must report offline, not raise — raising
    would open a source_offline ticket on every planning pass for a source
    nobody has subscribed to."""
    from explorer.adapters.api_football import APIFootballAdapter
    from explorer.adapters.odds_api import OddsAPIAdapter

    monkeypatch.delenv("EXPLORER_ODDS_API_KEY", raising=False)
    monkeypatch.delenv("EXPLORER_API_FOOTBALL_KEY", raising=False)
    for adapter in (OddsAPIAdapter(), APIFootballAdapter()):
        assert adapter.configured is False
        assert adapter.health() is False
        # Coverage is independent of configuration: conflating them would
        # report "not covered" for what is really "not subscribed".
        assert adapter.supports("premier_league") is True
        assert list(adapter.fetch_season("premier_league", "2023-2024")) == []


def test_understat_is_not_registered():
    """Its robots.txt is `Disallow: /` for every user agent. The site is
    reachable and the data is good; collecting it anyway would be ignoring an
    explicit instruction, which is not something to do quietly."""
    assert "understat" not in {a.name for a in build_default_registry()}
