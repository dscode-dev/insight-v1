"""MARKET_SNAPSHOT payload → ClickHouse row.

The incoming payload is the MARKET_SNAPSHOT derived-stream JSON
payload (the canonical shape is documented in tests/wire_payloads.py).

The output is a tuple of values in the same order as
`anvil.clickhouse.schemas.MARKET_SNAPSHOTS_COLUMNS`. Tuples are what
clickhouse-connect's `client.insert(table, data, column_names=...)` expects.

Decisions worth noting:

  * Decimal strings stay as strings here — `clickhouse-connect` accepts
    them and converts to ClickHouse `Decimal64` losslessly. We never go
    through `float`.
  * Outcome blocks are optional in the source payload (e.g. away leg not
    yet seen). Missing outcomes become NULL columns; the table is shaped
    Nullable(...) for those fields.
  * UUIDs and timestamps come in as ISO/canonical strings. clickhouse-connect
    coerces them into the underlying CH type given the column metadata.
"""

from __future__ import annotations

from typing import Any, Mapping


def map_market_snapshot_row(payload: Mapping[str, Any]) -> tuple[Any, ...]:
    """Translate a MARKET_SNAPSHOT payload dict into a column-ordered tuple.

    Raises:
        KeyError: if any required identity field is absent — handler treats
            this as a hard failure that surfaces to the consumer's retry path.
    """

    # snapshot_id doubles as the event_id on the wire. Both are
    # recorded so a future change to that identity doesn't break the row.
    snapshot_id = payload["snapshot_id"]
    event_id = payload.get("event_id", snapshot_id)

    outcomes = payload.get("outcomes") or {}
    home = outcomes.get("home") or {}
    draw = outcomes.get("draw") or {}
    away = outcomes.get("away") or {}

    return (
        event_id,
        snapshot_id,
        payload["match_id"],
        payload["region_code"],
        payload["market_type"],
        int(payload["state_version"]),
        int(home.get("calc_version") or draw.get("calc_version") or away.get("calc_version") or 1),
        payload.get("engine_version", ""),
        payload["watermark_event_ts"],
        payload["watermark_ingest_ts"],
        payload["generated_at"],
        # Home outcome
        home.get("best_odd"),
        home.get("best_bookmaker_id"),
        home.get("consensus_odd"),
        home.get("dispersion"),
        _opt_int(home.get("sample_size")),
        # Draw outcome
        draw.get("best_odd"),
        draw.get("best_bookmaker_id"),
        draw.get("consensus_odd"),
        draw.get("dispersion"),
        _opt_int(draw.get("sample_size")),
        # Away outcome
        away.get("best_odd"),
        away.get("best_bookmaker_id"),
        away.get("consensus_odd"),
        away.get("dispersion"),
        _opt_int(away.get("sample_size")),
        # Counts at the snapshot level
        int(payload["n_bookmakers_total"]),
        int(payload["n_bookmakers_valid"]),
    )


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None
