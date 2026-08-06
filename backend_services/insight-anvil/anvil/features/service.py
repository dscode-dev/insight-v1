"""Narrow read API used by Atlas through Insight Gateway."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from anvil.clickhouse.client import ClickHouseClient


class FeatureQueryService:
    def __init__(self, client: ClickHouseClient) -> None:
        self._client = client

    async def snapshot(
        self,
        *,
        match_id: UUID,
        as_of: datetime,
        pressure_window_seconds: int,
        market_window_seconds: int,
        signal_window_seconds: int,
        series_limit: int,
    ) -> dict[str, Any]:
        pressure = await self._one(
            """
            SELECT avg(human_pressure_home) AS home,
                   avg(human_pressure_away) AS away
            FROM metric_ticks
            WHERE match_id = {match_id:UUID}
              AND ts_ingest <= {as_of:DateTime64}
              AND ts_ingest >= {as_of:DateTime64} - INTERVAL {window:UInt32} SECOND
            """,
            {"match_id": match_id, "as_of": as_of, "window": pressure_window_seconds},
        )
        # `watermark_ingest_ts`, NOT `ts_ingest`: market_snapshots has no
        # such column and never did (0002_market_snapshots.sql), so this
        # query raised UNKNOWN_IDENTIFIER on every call — the market half
        # of the feature snapshot has never returned a value. The other
        # two tables here genuinely do have `ts_ingest`, which is why the
        # mistake looked consistent.
        #
        # `watermark_ingest_ts` is the right counterpart: the mapper
        # fills it from the same payload field that becomes `ts_ingest`
        # in metric_ticks (see mappers/market_snapshot.py).
        market = await self._one(
            """
            SELECT stddevPop(home_consensus_odd) AS volatility,
                   (anyLast(home_consensus_odd) - any(home_consensus_odd)) AS consensus_shift
            FROM market_snapshots
            WHERE match_id = {match_id:UUID}
              AND watermark_ingest_ts <= {as_of:DateTime64}
              AND watermark_ingest_ts >= {as_of:DateTime64} - INTERVAL {window:UInt32} SECOND
            """,
            {"match_id": match_id, "as_of": as_of, "window": market_window_seconds},
        )
        signals = await self._one(
            """
            SELECT count() AS signal_count
            FROM human_signals
            WHERE match_id = {match_id:UUID}
              AND ts_ingest <= {as_of:DateTime64}
              AND ts_ingest >= {as_of:DateTime64} - INTERVAL {window:UInt32} SECOND
            """,
            {"match_id": match_id, "as_of": as_of, "window": signal_window_seconds},
        )
        series = await self._many(
            """
            SELECT human_pressure_home AS home, human_pressure_away AS away
            FROM metric_ticks
            WHERE match_id = {match_id:UUID}
              AND ts_ingest <= {as_of:DateTime64}
            ORDER BY ts_ingest DESC
            LIMIT {limit:UInt32}
            """,
            {"match_id": match_id, "as_of": as_of, "limit": series_limit},
        )
        # `minute` is NOT queried, because `metric_ticks` has no such
        # column: it is absent from 0003_metric_ticks.sql AND from
        # mappers/metric_tick.py, so nothing has ever written it. The
        # query that used to be here failed with UNKNOWN_IDENTIFIER,
        # which took down the ENTIRE snapshot — pressure, market,
        # signals and series all returned 500 because of this one field.
        #
        # Reporting None keeps the other four features working and
        # matches the contract (Atlas's `match_minute` is already
        # `int | None`). Restoring the feature for real needs a `minute`
        # column in the DDL and a mapper that populates it from the
        # derived event — a schema decision, not a fix to make here.
        minute: dict[str, Any] = {}
        return {
            "match_id": str(match_id),
            "as_of": as_of.isoformat(),
            "pressure": {
                "home": _number(pressure.get("home")),
                "away": _number(pressure.get("away")),
            },
            "market": {
                "volatility": _number(market.get("volatility")),
                "consensus_shift": _number(market.get("consensus_shift")),
            },
            "signal_count": int(signals.get("signal_count") or 0),
            "pressure_series": [
                {"home": _number(row.get("home")), "away": _number(row.get("away"))}
                for row in reversed(series)
            ],
            "minute": _integer(minute.get("minute")),
        }

    async def _one(self, sql: str, parameters: dict[str, Any]) -> dict[str, Any]:
        rows = await self._many(sql, parameters)
        return rows[0] if rows else {}

    async def _many(
        self, sql: str, parameters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        result = await self._client.query(sql, parameters=parameters)
        return [dict(row) for row in result.named_results()]


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
