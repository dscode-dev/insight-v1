from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from anvil.features import FeatureQueryService

# This stub is why three schema bugs survived to production: it answered
# whatever the query asked for, including a `minute` column the real
# metric_ticks table never had. `test_feature_query_columns.py` checks
# the SQL against the actual DDL, which is the part a stub cannot do.


class Result:
    def __init__(self, rows):
        self._rows = rows

    def named_results(self):
        return self._rows


class Client:
    def __init__(self):
        self.calls = 0

    async def query(self, sql, *, parameters=None):
        self.calls += 1
        if "avg(human_pressure_home)" in sql:
            return Result([{"home": 0.7, "away": 0.4}])
        if "stddevPop" in sql:
            return Result([{"volatility": 0.1, "consensus_shift": -0.02}])
        if "count()" in sql:
            return Result([{"signal_count": 8}])
        if "ORDER BY ts_ingest DESC" in sql:
            return Result([
                {"home": 0.8, "away": 0.2},
                {"home": 0.6, "away": 0.4},
            ])
        raise AssertionError(f"unexpected query: {sql}")


def test_feature_query_service_returns_contract() -> None:
    client = Client()
    payload = asyncio.run(
        FeatureQueryService(client).snapshot(
            match_id=uuid4(),
            as_of=datetime.now(timezone.utc),
            pressure_window_seconds=300,
            market_window_seconds=600,
            signal_window_seconds=600,
            series_limit=6,
        )
    )
    assert payload["pressure"] == {"home": 0.7, "away": 0.4}
    assert payload["market"] == {"volatility": 0.1, "consensus_shift": -0.02}
    assert payload["signal_count"] == 8
    assert payload["pressure_series"][0] == {"home": 0.6, "away": 0.4}
    # `minute` is reported as None and NOT queried: metric_ticks has no
    # such column — it is absent from the DDL and from the mapper, so
    # nothing ever wrote it. The query that used to be here failed with
    # UNKNOWN_IDENTIFIER and took the WHOLE snapshot down with it.
    # Restoring the feature needs a schema change, not a query fix.
    assert payload["minute"] is None
    # Four queries, not five — the minute query is gone.
    assert client.calls == 4
