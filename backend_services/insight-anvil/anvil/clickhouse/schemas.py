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
