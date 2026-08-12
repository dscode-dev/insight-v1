"""Authoritative column lists per table.

The migrations SQL is the source of truth for the actual DDL. This module
just enumerates the column order — `clickhouse-connect.insert(table,
data, column_names=...)` needs it to bind positional values to columns
correctly. Keep this list in lockstep with the DDL.
"""

from __future__ import annotations

from typing import Final


# Names mirror the DDL exactly. Tests assert that this list matches what
# CH reports via `DESCRIBE TABLE`, which catches accidental drift.

MARKET_SNAPSHOTS_TABLE: Final[str] = "market_snapshots"
MARKET_SNAPSHOTS_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "snapshot_id",
    "match_id",
    "region_code",
    "market_type",
    "state_version",
    "calc_version",
    "engine_version",
    "watermark_event_ts",
    "watermark_ingest_ts",
    "generated_at",
    "home_best_odd",
    "home_best_bookmaker_id",
    "home_consensus_odd",
    "home_dispersion",
    "home_sample_size",
    "draw_best_odd",
    "draw_best_bookmaker_id",
    "draw_consensus_odd",
    "draw_dispersion",
    "draw_sample_size",
    "away_best_odd",
    "away_best_bookmaker_id",
    "away_consensus_odd",
    "away_dispersion",
    "away_sample_size",
    "n_bookmakers_total",
    "n_bookmakers_valid",
)


METRIC_TICKS_TABLE: Final[str] = "metric_ticks"
METRIC_TICKS_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "match_id",
    "region_code",
    "market_type",
    "state_version",
    "schema_version",
    "calc_version",
    "engine_version",
    "correlation_id",
    "source",
    "ts_event_max",
    "ts_ingest",
    "quality",
    "flags",
    "n_bookmakers_total",
    "n_bookmakers_valid",
    "consensus_home",
    "consensus_draw",
    "consensus_away",
    "dispersion_home",
    "dispersion_draw",
    "dispersion_away",
    "volatility_home",
    "volatility_draw",
    "volatility_away",
    "liquidity_score",
    "stability_score",
    "shock_score",
    "market_calc_version",
    "human_quorum",
    "human_confidence",
    "human_coordination_score",
    "human_pressure_home",
    "human_pressure_away",
    "human_effort_home",
    "human_effort_away",
    "human_ref_pressure",
    "human_calc_version",
    "xp_home",
    "xp_away",
    "xr_home",
    "xr_away",
    "derived_calc_version",
)


HUMAN_SIGNALS_TABLE: Final[str] = "human_signals"
HUMAN_SIGNALS_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "match_id",
    "user_id",
    "region_code",
    "signal_type",
    "ts_event",
    "ts_ingest",
    "minute",
    "value",
    "weight",
    "reputation_score",
    "abuse_decision",
    "weight_multiplier",
)


# --- historical tables (the Explorer's five-year backfill) -----------------
#
# Separate from the three above because they describe a different thing: one
# row per fixture, no state_version, and no TTL. See the migrations for why
# writing history into the live-match tables would key it wrongly and delete
# it after ninety days.

HISTORICAL_FIXTURES_TABLE: Final[str] = "historical_fixtures"
HISTORICAL_FIXTURES_COLUMNS: Final[tuple[str, ...]] = (
    "external_fixture_id",
    "source",
    "competition_key",
    "season",
    "match_id",
    "scheduled_at",
    "home_team_name",
    "away_team_name",
    "home_club_id",
    "away_club_id",
    "status",
    "home_score",
    "away_score",
    "halftime_home_score",
    "halftime_away_score",
    "trust_level",
    "confidence",
    "captured_at",
)

HISTORICAL_ODDS_TABLE: Final[str] = "historical_odds"
HISTORICAL_ODDS_COLUMNS: Final[tuple[str, ...]] = (
    "external_fixture_id",
    "source",
    "competition_key",
    "season",
    "bookmaker",
    "market",
    "captured_at",
    "home_price",
    "draw_price",
    "away_price",
    "extra_selections",
    "trust_level",
    "confidence",
)

HISTORICAL_STATS_TABLE: Final[str] = "historical_stats"
HISTORICAL_STATS_COLUMNS: Final[tuple[str, ...]] = (
    "external_fixture_id",
    "source",
    "competition_key",
    "season",
    "home_shots",
    "home_shots_on_target",
    "home_corners",
    "home_fouls",
    "home_offsides",
    "home_yellow_cards",
    "home_red_cards",
    "home_possession",
    "home_expected_goals",
    "away_shots",
    "away_shots_on_target",
    "away_corners",
    "away_fouls",
    "away_offsides",
    "away_yellow_cards",
    "away_red_cards",
    "away_possession",
    "away_expected_goals",
    "trust_level",
    "confidence",
    "captured_at",
)
