"""Historical baselines, read back for Atlas.

    ClickHouse (historical_*)  →  THIS  →  Atlas

WHY THIS IS THE POINT OF THE WHOLE BACKFILL. Collecting five years and
storing it is worth nothing on its own. Atlas's job is to say what is
happening now, and "unusual" is undefinable without something to be unusual
against. Every query here answers one form of the same question:

    is what I am seeing normal for these teams, in this competition?

Three consumers, all of them Atlas:

  * DURING a live match — a pressure or market reading arrives, and the
    engine needs the baseline to decide whether it is a trend or noise.
  * BEFORE a match — the pre-match context: how these two have met, what
    the market usually makes of each of them.
  * AFTER a match — the review: which numbers actually departed from
    normal, which is the same comparison read backwards.

WHAT IT DELIBERATELY DOES NOT DO. It returns measurements, never verdicts.
No "team A is stronger", no probability, no prediction — `ATLAS_V1_FROZEN.md`
makes Atlas descriptive, and a store that shipped conclusions would move that
decision somewhere nobody is looking at the guardrails.

SAMPLE SIZE TRAVELS WITH EVERY NUMBER. An average over three matches and one
over three hundred are different claims. Returning the mean alone lets the
caller treat them the same, which is how a coincidence becomes a trend.

TEAMS ARE ADDRESSED BY club_id, NEVER BY THE SOURCE'S SPELLING. Three
sources write the same club three ways — `Barcelona`, `FC Barcelona`,
`Betis` / `Real Betis` / `Real Betis Balompié` — and every one of them is
stored, because the raw name is what the source actually said. Filtering on
it answers with a fraction of the history and no indication that anything is
missing: `home_team_name = 'Barcelona'` matched 92 of Barcelona's 236
matches, so a baseline built that way was computed over 39% of the record
while reporting a sample_size that looked entirely plausible. `home_club_id`
is the resolved identity and is populated on every row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from anvil.clickhouse.client import ClickHouseClient

logger = logging.getLogger(__name__)

# Bounded so one query cannot scan every season ever collected. A baseline
# built from more than this stops changing anyway.
_MAX_SEASONS = 10
_MAX_MATCHES = 500

# Descending trust, as a ClickHouse expression, for picking between sources
# that disagree. A literal — no caller input reaches it — and it mirrors
# `_SOURCE_RANK` in scripts/atlas_similarity_dataset_build.py so the hot path
# and the cold path resolve a conflict the same way.
_SOURCE_RANK_SQL = (
    "multiIf(source = 'statsbomb', 0, source = 'football_data', 1, 2)"
)


@dataclass
class HistoricalFeatureService:
    client: ClickHouseClient
    database: str = "insight"

    # --- team baselines ---------------------------------------------------

    async def team_baseline(
        self,
        *,
        club_id: str,
        competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """What this team's matches usually look like.

        Home and away are reported SEPARATELY, never pooled. Home advantage
        is one of the largest and most stable effects in the sport; a single
        blended average would hide it and make every home fixture look
        slightly surprising.
        """
        season_filter, params = _season_filter(seasons)
        params.update({"team": club_id, "competition": competition_key})

        query = f"""
            SELECT
                countIf(home_club_id = {{team:String}})            AS home_matches,
                countIf(away_club_id = {{team:String}})            AS away_matches,
                avgIf(home_score, home_club_id = {{team:String}})  AS home_goals_for,
                avgIf(away_score, home_club_id = {{team:String}})  AS home_goals_against,
                avgIf(away_score, away_club_id = {{team:String}})  AS away_goals_for,
                avgIf(home_score, away_club_id = {{team:String}})  AS away_goals_against
            FROM {self.database}.historical_fixtures
            WHERE competition_key = {{competition:String}}
              AND status = 'finished'
              AND (home_club_id = {{team:String}} OR away_club_id = {{team:String}})
              {season_filter}
        """
        row = await self._one(query, params)

        home_matches = _int(row.get("home_matches"))
        away_matches = _int(row.get("away_matches"))
        return {
            "club_id": club_id,
            "competition_key": competition_key,
            "seasons": seasons or "all",
            "home": {
                "matches": home_matches,
                "goals_for_avg": _round(row.get("home_goals_for")),
                "goals_against_avg": _round(row.get("home_goals_against")),
            },
            "away": {
                "matches": away_matches,
                "goals_for_avg": _round(row.get("away_goals_for")),
                "goals_against_avg": _round(row.get("away_goals_against")),
            },
            # The caller decides what to do with a thin baseline. Suppressing
            # it here would hide the reason a conclusion is weak.
            "sample_size": home_matches + away_matches,
        }

    async def team_stats_baseline(
        self,
        *,
        club_id: str,
        competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """Typical shot/corner/card volumes, for comparing a live reading.

        `stddevPop` travels with each mean: "fourteen shots" is only
        remarkable relative to how much this team's shot count normally
        varies, and a mean with no spread invites treating one good match as
        a change in behaviour.
        """
        season_filter, params = _season_filter(seasons, table_alias="s")
        params.update({"team": club_id, "competition": competition_key})

        query = f"""
            SELECT
                count()                                   AS matches,
                avg(shots)                                AS shots_avg,
                stddevPop(shots)                          AS shots_stddev,
                avg(shots_on_target)                      AS shots_on_target_avg,
                avg(corners)                              AS corners_avg,
                avg(yellow_cards)                         AS yellow_cards_avg
            FROM (
                SELECT
                    if(f.home_club_id = {{team:String}}, s.home_shots, s.away_shots) AS shots,
                    if(f.home_club_id = {{team:String}}, s.home_shots_on_target, s.away_shots_on_target) AS shots_on_target,
                    if(f.home_club_id = {{team:String}}, s.home_corners, s.away_corners) AS corners,
                    if(f.home_club_id = {{team:String}}, s.home_yellow_cards, s.away_yellow_cards) AS yellow_cards
                FROM {self.database}.historical_stats AS s
                INNER JOIN {self.database}.historical_fixtures AS f
                    ON f.external_fixture_id = s.external_fixture_id
                   AND f.source = s.source
                WHERE s.competition_key = {{competition:String}}
                  AND (f.home_club_id = {{team:String}} OR f.away_club_id = {{team:String}})
                  {season_filter}
            )
        """
        row = await self._one(query, params)
        matches = _int(row.get("matches"))
        return {
            "club_id": club_id,
            "competition_key": competition_key,
            "matches": matches,
            "shots": {"avg": _round(row.get("shots_avg")),
                      "stddev": _round(row.get("shots_stddev"))},
            "shots_on_target": {"avg": _round(row.get("shots_on_target_avg"))},
            "corners": {"avg": _round(row.get("corners_avg"))},
            "yellow_cards": {"avg": _round(row.get("yellow_cards_avg"))},
            "sample_size": matches,
        }

    # --- head to head -----------------------------------------------------

    async def head_to_head(
        self,
        *,
        home_club_id: str,
        away_club_id: str,
        competition_key: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Previous meetings, newest first, one row per meeting.

        Not aggregated into a win count: the pre-match context wants the
        matches themselves — when, where, what the score was. A "3-1-2"
        summary discards the recency and the venue, which is most of what
        makes a previous meeting relevant.

        GROUPED BY MATCH, NOT BY ROW. Every source that covered a meeting
        stored its own row, so an ungrouped `LIMIT 10` returned about three
        actual meetings wearing ten faces — and a caller counting them read
        three times the head-to-head history that exists.

        The day, not the timestamp, identifies the meeting: Football-Data
        publishes no kickoff time and stores midnight where openfootball
        stores 19:30. `max(scheduled_at)` then reports the informative one.
        """
        params: dict[str, Any] = {
            "home": home_club_id,
            "away": away_club_id,
            "limit": min(max(limit, 1), _MAX_MATCHES),
        }
        competition_filter = ""
        if competition_key:
            competition_filter = "AND competition_key = {competition:String}"
            params["competition"] = competition_key

        query = f"""
            SELECT
                toDate(scheduled_at)          AS match_day,
                home_club_id, away_club_id,
                -- NOT aliased back to `scheduled_at`: the GROUP BY key is
                -- `toDate(scheduled_at)`, and reusing the column's own name
                -- for an aggregate over it makes ClickHouse resolve the key
                -- to the aggregate — ILLEGAL_AGGREGATION, code 184.
                max(scheduled_at)             AS kickoff_at,
                any(competition_key)          AS competition_key,
                any(season)                   AS season,
                groupUniqArray(source)        AS sources,
                -- Where sources disagree about a score, the most-reviewed one
                -- wins: StatsBomb is hand-curated, Football-Data is a
                -- maintained archive, openfootball is community-edited. Same
                -- ranking as scripts/atlas_similarity_dataset_build.py, so the
                -- hot and cold paths cannot report different final scores.
                argMin(external_fixture_id, {_SOURCE_RANK_SQL}) AS external_fixture_id,
                argMin(home_team_name, {_SOURCE_RANK_SQL})      AS home_team_name,
                argMin(away_team_name, {_SOURCE_RANK_SQL})      AS away_team_name,
                argMin(home_score, {_SOURCE_RANK_SQL})          AS home_score,
                argMin(away_score, {_SOURCE_RANK_SQL})          AS away_score
            FROM {self.database}.historical_fixtures
            WHERE status = 'finished'
              AND (
                (home_club_id = {{home:String}} AND away_club_id = {{away:String}})
                OR
                (home_club_id = {{away:String}} AND away_club_id = {{home:String}})
              )
              {competition_filter}
            GROUP BY match_day, home_club_id, away_club_id
            ORDER BY kickoff_at DESC
            LIMIT {{limit:UInt32}}
        """
        rows = await self._many(query, params)
        return {
            "home_club_id": home_club_id,
            "away_club_id": away_club_id,
            "competition_key": competition_key,
            "meetings": rows,
            "sample_size": len(rows),
        }

    # --- market baselines -------------------------------------------------

    async def market_baseline(
        self,
        *,
        competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """What the market normally looks like in this competition.

        Consensus price and the DISPERSION between books. Dispersion is the
        half that matters for detecting something unusual: bookmakers
        disagreeing more than they normally do is a signal, and it is
        invisible if only the average price is kept.
        """
        season_filter, params = _season_filter(seasons)
        params["competition"] = competition_key

        query = f"""
            SELECT
                count()                       AS quotes,
                uniqExact(external_fixture_id) AS fixtures,
                uniqExact(bookmaker)          AS bookmakers,
                avg(home_price)               AS home_avg,
                avg(draw_price)               AS draw_avg,
                avg(away_price)               AS away_avg,
                stddevPop(home_price)         AS home_dispersion,
                stddevPop(draw_price)         AS draw_dispersion,
                stddevPop(away_price)         AS away_dispersion
            FROM {self.database}.historical_odds
            WHERE competition_key = {{competition:String}}
              AND market = '1x2'
              AND bookmaker NOT LIKE '\\\\_market\\\\_%'
              {season_filter}
        """
        row = await self._one(query, params)
        return {
            "competition_key": competition_key,
            "seasons": seasons or "all",
            "quotes": _int(row.get("quotes")),
            "fixtures": _int(row.get("fixtures")),
            "bookmakers": _int(row.get("bookmakers")),
            "home": {"avg": _round(row.get("home_avg")),
                     "dispersion": _round(row.get("home_dispersion"))},
            "draw": {"avg": _round(row.get("draw_avg")),
                     "dispersion": _round(row.get("draw_dispersion"))},
            "away": {"avg": _round(row.get("away_avg")),
                     "dispersion": _round(row.get("away_dispersion"))},
            "sample_size": _int(row.get("quotes")),
        }

    async def coverage(self) -> dict[str, Any]:
        """What history actually exists, per competition and season.

        The first thing to check when a baseline looks wrong: an empty
        answer from a query is indistinguishable from a team that never
        played, unless you can see what the store holds.
        """
        query = f"""
            SELECT competition_key, season,
                   count() AS fixtures,
                   min(scheduled_at) AS first_match,
                   max(scheduled_at) AS last_match
            FROM {self.database}.historical_fixtures
            GROUP BY competition_key, season
            ORDER BY competition_key, season
        """
        rows = await self._many(query, {})
        return {"coverage": rows, "seasons": len(rows)}


    # --- result access ----------------------------------------------------
    #
    # clickhouse-connect returns a QueryResult, not a list of dicts.
    # Indexing it directly yields tuples, so `row.get("matches")` would raise
    # AttributeError on the first real query — through one helper, that
    # cannot be got wrong per call site.

    async def _many(self, sql: str, parameters: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self.client.query(sql, parameters=parameters or None)
        return [_jsonable(dict(row)) for row in result.named_results()]

    async def _one(self, sql: str, parameters: dict[str, Any]) -> dict[str, Any]:
        rows = await self._many(sql, parameters)
        return rows[0] if rows else {}


# --- helpers ---------------------------------------------------------------

def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Dates and datetimes out of ClickHouse, as ISO strings.

    `clickhouse-connect` maps Date/DateTime columns to Python `date`/
    `datetime`, and the health server serialises with the stdlib `json`,
    which refuses both — `TypeError: Object of type datetime is not JSON
    serializable`, a 500 with the query already successful behind it.

    Applied here rather than per call site so the endpoints that select a
    timestamp (head-to-head's kickoff, coverage's first/last match) cannot
    each be got right or wrong separately. It surfaced only now because
    these routes had never been called by anything.
    """
    return {
        key: value.isoformat() if isinstance(value, (date, datetime)) else value
        for key, value in row.items()
    }

def _season_filter(
    seasons: list[str] | None, table_alias: str = "",
) -> tuple[str, dict[str, Any]]:
    """Build the optional season restriction.

    Parameterised, never interpolated: a season label reaches this from an
    HTTP query string, and building SQL by concatenation is how that becomes
    an injection.
    """
    if not seasons:
        return "", {}
    bounded = seasons[:_MAX_SEASONS]
    column = f"{table_alias}.season" if table_alias else "season"
    return f"AND {column} IN {{seasons:Array(String)}}", {"seasons": bounded}


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _round(value: Any) -> float | None:
    """None stays None — it means "not measured", which a 0.0 would hide."""
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
