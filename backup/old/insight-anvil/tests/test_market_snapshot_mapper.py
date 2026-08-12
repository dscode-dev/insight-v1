"""Mapper test: the canonical MARKET_SNAPSHOT wire payload must map to
a row whose values land in the correct columns of
`MARKET_SNAPSHOTS_COLUMNS`.

The payload shape comes from tests/wire_payloads.py — the derived
stream's documented JSON contract.
"""

from __future__ import annotations

from uuid import uuid4

from anvil.clickhouse.schemas import MARKET_SNAPSHOTS_COLUMNS
from anvil.mappers import map_market_snapshot_row

from .wire_payloads import market_snapshot_payload, outcome_aggregation


def test_mapper_emits_value_for_every_column():
    row = map_market_snapshot_row(market_snapshot_payload())
    assert len(row) == len(MARKET_SNAPSHOTS_COLUMNS), (
        "row arity must match MARKET_SNAPSHOTS_COLUMNS — drift = silent column shift"
    )


def test_mapper_field_positions_match_schema_order():
    """Spot-check a handful of column positions so a refactor that
    reorders MARKET_SNAPSHOTS_COLUMNS without updating the mapper fails loudly."""
    match_id = uuid4()
    row = map_market_snapshot_row(
        market_snapshot_payload(match_id=match_id, state_version=42)
    )

    cols = MARKET_SNAPSHOTS_COLUMNS
    assert row[cols.index("match_id")] == str(match_id)
    assert row[cols.index("region_code")] == "BR_NE"
    assert row[cols.index("market_type")] == "FT_1X2"
    assert row[cols.index("state_version")] == 42
    assert row[cols.index("n_bookmakers_total")] == 6
    assert row[cols.index("n_bookmakers_valid")] == 6
    # Home outcome
    assert str(row[cols.index("home_best_odd")]) == "2.10"
    assert str(row[cols.index("home_consensus_odd")]) == "2.12"
    assert str(row[cols.index("home_dispersion")]) == "0.05"
    assert row[cols.index("home_sample_size")] == 6


def test_mapper_handles_partial_outcomes():
    """A snapshot with only the home leg should produce NULL columns for the
    missing legs, not raise."""
    row = map_market_snapshot_row(market_snapshot_payload(
        outcomes={
            "home": outcome_aggregation(
                best_odd="2.10", consensus_odd="2.12",
                dispersion="0.05", sample_size=3,
            ),
        },
    ))
    cols = MARKET_SNAPSHOTS_COLUMNS
    assert row[cols.index("draw_best_odd")] is None
    assert row[cols.index("draw_sample_size")] is None
    assert row[cols.index("away_best_odd")] is None
    assert row[cols.index("away_consensus_odd")] is None
