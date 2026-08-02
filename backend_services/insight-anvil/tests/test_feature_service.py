from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from anvil.features import FeatureQueryService


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
        return Result([{"minute": 73}])


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
    assert payload["minute"] == 73
    assert client.calls == 5
