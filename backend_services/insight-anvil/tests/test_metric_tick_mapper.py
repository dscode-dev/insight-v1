"""Mapper test for the METRIC_TICK wire payload → metric_ticks row.

Round-trips the canonical wire payload (tests/wire_payloads.py) and
asserts column positions + arity.
"""

from __future__ import annotations

from uuid import uuid4

from anvil.clickhouse.schemas import METRIC_TICKS_COLUMNS
from anvil.mappers import map_metric_tick_row

from .wire_payloads import metric_tick_payload


def test_mapper_emits_value_for_every_column():
    row = map_metric_tick_row(metric_tick_payload())
    assert len(row) == len(METRIC_TICKS_COLUMNS), (
        "row arity must match METRIC_TICKS_COLUMNS — drift = silent column shift"
    )


def test_mapper_flattens_nested_market_human_derived_blocks():
    match_id = uuid4()
    row = map_metric_tick_row(
        metric_tick_payload(match_id=match_id, state_version=99)
    )
    cols = METRIC_TICKS_COLUMNS

    assert row[cols.index("match_id")] == str(match_id)
    assert row[cols.index("state_version")] == 99
    # market.* should be flattened into top-level columns
    assert str(row[cols.index("consensus_home")]) == "2.10"
    assert str(row[cols.index("dispersion_home")]) == "0.05"
    assert str(row[cols.index("liquidity_score")]) == "0.65"
    # human.*
    assert row[cols.index("human_quorum")] == 42
    assert str(row[cols.index("human_pressure_home")]) == "0.70"
    # derived.*
    assert str(row[cols.index("xp_home")]) == "0.48"
    assert row[cols.index("xr_home")] is None
    # flags
    assert set(row[cols.index("flags")]) == {"HIGH_SHOCK", "LOW_QUORUM"}
