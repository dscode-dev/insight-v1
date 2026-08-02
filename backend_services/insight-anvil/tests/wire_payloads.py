"""Canonical derived-event wire payloads for tests.

These builders produce the exact JSON shapes the derived stream
carries (historically the JSON-mode dump of the retired Magnus
models). Anvil owns this contract now: the mappers consume plain
dicts, so the tests document and exercise the wire format directly
instead of importing legacy model classes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def outcome_aggregation(
    *,
    best_odd: str,
    consensus_odd: str,
    dispersion: str,
    sample_size: int = 6,
    calc_version: int = 1,
) -> dict:
    return {
        "best_odd": best_odd,
        "best_bookmaker_id": str(uuid4()),
        "consensus_odd": consensus_odd,
        "sample_size": sample_size,
        "dispersion": dispersion,
        "calc_version": calc_version,
    }


def market_snapshot_payload(
    *,
    match_id=None,
    state_version: int = 1,
    outcomes: dict | None = None,
) -> dict:
    if outcomes is None:
        outcomes = {
            "home": outcome_aggregation(
                best_odd="2.10", consensus_odd="2.12", dispersion="0.05"
            ),
            "draw": outcome_aggregation(
                best_odd="3.20", consensus_odd="3.18", dispersion="0.08"
            ),
            "away": outcome_aggregation(
                best_odd="3.80", consensus_odd="3.75", dispersion="0.06"
            ),
        }
    return {
        "snapshot_id": str(uuid4()),
        "match_id": str(match_id or uuid4()),
        "region_code": "BR_NE",
        "market_type": "FT_1X2",
        "state_version": state_version,
        "outcomes": outcomes,
        "n_bookmakers_total": 6,
        "n_bookmakers_valid": 6,
        "watermark_event_ts": utcnow_iso(),
        "watermark_ingest_ts": utcnow_iso(),
        "generated_at": utcnow_iso(),
    }


def metric_tick_payload(*, match_id=None, state_version: int = 1) -> dict:
    return {
        "event_id": str(uuid4()),
        "match_id": str(match_id or uuid4()),
        "region_code": "BR_NE",
        "market_type": "FT_1X2",
        "schema_version": 1,
        "calc_version": 1,
        "engine_version": "magnus.D4",
        "state_version": state_version,
        "ts_event_max": utcnow_iso(),
        "ts_ingest": utcnow_iso(),
        "quality": "0.78",
        "flags": ["HIGH_SHOCK", "LOW_QUORUM"],
        "market": {
            "n_bookmakers_total": 6,
            "n_bookmakers_valid": 6,
            "consensus_home": "2.10",
            "consensus_draw": "3.20",
            "consensus_away": "3.80",
            "dispersion_home": "0.05",
            "dispersion_draw": "0.08",
            "dispersion_away": "0.06",
            "volatility_home": "0.12",
            "volatility_draw": "0.08",
            "volatility_away": "0.10",
            "liquidity_score": "0.65",
            "stability_score": "0.90",
            "shock_score": "0.20",
            "calc_version": 1,
        },
        "human": {
            "quorum": 42,
            "confidence": "0.55",
            "coordination_score": "0.10",
            "pressure_home": "0.70",
            "pressure_away": "0.30",
            "effort_home": "0.40",
            "effort_away": "0.20",
            "ref_pressure": "0.15",
            "calc_version": 1,
        },
        "derived": {
            "xP_home": "0.48",
            "xP_away": "0.21",
            "xR_home": None,
            "xR_away": None,
            "calc_version": 1,
        },
        "correlation_id": str(uuid4()),
        "source": "magnus",
    }
