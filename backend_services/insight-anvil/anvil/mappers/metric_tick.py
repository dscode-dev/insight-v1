"""METRIC_TICK payload → ClickHouse row.

Source: the METRIC_TICK derived-stream JSON payload (the canonical
shape is documented in tests/wire_payloads.py).

The MetricTick is already flat-ish — `market`, `human`, `derived` are
nested objects with primitive leaves. We flatten them into a column-ordered
tuple matching `anvil.clickhouse.schemas.METRIC_TICKS_COLUMNS`.

Decisions worth noting:

  * `flags` becomes `Array(LowCardinality(String))`. We coerce to a list
    of strings so an upstream `set` / `tuple` shape still works.
  * Nullable nested fields (consensus_home etc.) flow through as None
    when absent — handled by the table's Nullable(Decimal64) columns.
  * `correlation_id` is `Optional[UUID]` upstream; pass None through.
"""

from __future__ import annotations

from typing import Any, Mapping


def map_metric_tick_row(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    market = payload.get("market") or {}
    human = payload.get("human") or {}
    derived = payload.get("derived") or {}

    flags = payload.get("flags") or []
    if not isinstance(flags, list):
        flags = list(flags)

    return (
        payload["event_id"],
        payload["match_id"],
        payload["region_code"],
        payload["market_type"],
        int(payload["state_version"]),
        int(payload.get("schema_version") or 1),
        int(payload.get("calc_version") or 1),
        payload.get("engine_version", ""),
        payload.get("correlation_id"),
        payload.get("source", "magnus"),
        payload["ts_event_max"],
        payload["ts_ingest"],
        payload.get("quality", "0"),
        flags,
        # ---- market features ------------------------------------------------
        int(market.get("n_bookmakers_total") or 0),
        int(market.get("n_bookmakers_valid") or 0),
        market.get("consensus_home"),
        market.get("consensus_draw"),
        market.get("consensus_away"),
        market.get("dispersion_home"),
        market.get("dispersion_draw"),
        market.get("dispersion_away"),
        market.get("volatility_home", "0"),
        market.get("volatility_draw", "0"),
        market.get("volatility_away", "0"),
        market.get("liquidity_score", "0"),
        market.get("stability_score", "0"),
        market.get("shock_score", "0"),
        int(market.get("calc_version") or 1),
        # ---- human features -------------------------------------------------
        int(human.get("quorum") or 0),
        human.get("confidence", "0"),
        human.get("coordination_score", "0"),
        human.get("pressure_home", "0"),
        human.get("pressure_away", "0"),
        human.get("effort_home", "0"),
        human.get("effort_away", "0"),
        human.get("ref_pressure", "0"),
        int(human.get("calc_version") or 1),
        # ---- derived metrics ------------------------------------------------
        derived.get("xP_home", "0"),
        derived.get("xP_away", "0"),
        derived.get("xR_home"),
        derived.get("xR_away"),
        int(derived.get("calc_version") or 1),
    )
