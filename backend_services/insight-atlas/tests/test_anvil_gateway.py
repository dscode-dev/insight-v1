from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx

from atlas.clients.anvil_gateway import AnvilGatewayReader


async def test_anvil_gateway_reader_maps_feature_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Atlas-Anvil-Key"] == "k" * 32
        return httpx.Response(
            200,
            json={
                "pressure": {"home": 0.7, "away": 0.4},
                "market": {"volatility": 0.12, "consensus_shift": -0.03},
                "signal_count": 9,
                "pressure_series": [
                    {"home": 0.5, "away": 0.5},
                    {"home": 0.7, "away": 0.3},
                ],
                "minute": 72,
            },
        )

    reader = AnvilGatewayReader(
        base_url="https://gateway.test/v1",
        api_key="k" * 32,
    )
    await reader._client.aclose()
    reader._client = httpx.AsyncClient(
        base_url="https://gateway.test/v1",
        headers={"X-Atlas-Anvil-Key": "k" * 32},
        transport=httpx.MockTransport(handler),
    )
    match_id = uuid4()
    now = datetime.now(timezone.utc)
    assert await reader.pressure_means(
        match_id=match_id, as_of=now, window_seconds=300
    ) == (0.7, 0.4)
    assert await reader.consensus_movement(
        match_id=match_id, as_of=now, window_seconds=600
    ) == (0.12, -0.03)
    assert await reader.signal_count(
        match_id=match_id, as_of=now, window_seconds=600
    ) == 9
    assert await reader.pressure_series(
        match_id=match_id, as_of=now, limit=6
    ) == [(0.5, 0.5), (0.7, 0.3)]
    assert await reader.match_minute(match_id=match_id, as_of=now) == 72
    await reader.aclose()
