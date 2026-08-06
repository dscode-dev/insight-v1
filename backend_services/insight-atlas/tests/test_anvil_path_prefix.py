"""The Anvil feature-read path depends on who sits between Atlas and Anvil.

Gateway-mediated (default): Atlas asks the Insight Gateway for
`/internal/anvil/features/matches/{id}` and the gateway rewrites it onto
the `/internal/features/matches/{id}` that Anvil serves.

Direct (Anvil colocated with Atlas): nothing performs that rewrite, so
the default prefix 404s. This is silent in the worst way — a 404 from
the analytics reader surfaces as a degraded feature snapshot, not as a
configuration error.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from atlas.clients.anvil_gateway import (
    DEFAULT_API_KEY_HEADER,
    DEFAULT_FEATURES_PATH_PREFIX,
    DIRECT_API_KEY_HEADER,
    DIRECT_FEATURES_PATH_PREFIX,
    AnvilGatewayReader,
)

KEY = "k" * 32
MATCH_ID = uuid4()
AS_OF = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


def _reader(**kwargs) -> tuple[AnvilGatewayReader, list[str], list[dict]]:
    """Reader wired to a transport recording the paths AND headers sent."""
    seen: list[str] = []
    sent_headers: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        sent_headers.append(dict(request.headers))
        return httpx.Response(200, json={})

    reader = AnvilGatewayReader(base_url="http://anvil:8081", api_key=KEY, **kwargs)
    # Swap only the transport — the headers the constructor built are
    # what we are testing, so they must be preserved.
    reader._client = httpx.AsyncClient(
        base_url="http://anvil:8081",
        transport=httpx.MockTransport(handler),
        headers=reader._client.headers,
    )
    return reader, seen, sent_headers


@pytest.mark.asyncio
async def test_defaults_to_the_gateway_route():
    reader, seen, _headers = _reader()
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    assert seen == [f"{DEFAULT_FEATURES_PATH_PREFIX}/matches/{MATCH_ID}"]
    # The default must stay gateway-facing: every existing deployment
    # reaches Anvil through the gateway, and flipping this default would
    # break them all at once.
    assert DEFAULT_FEATURES_PATH_PREFIX == "/internal/anvil/features"


@pytest.mark.asyncio
async def test_direct_prefix_targets_the_route_anvil_actually_serves():
    reader, seen, _headers = _reader(features_path_prefix=DIRECT_FEATURES_PATH_PREFIX)
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    # anvil/runtime/health.py serves exactly this prefix.
    assert seen == [f"/internal/features/matches/{MATCH_ID}"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "given",
    ["/internal/features", "internal/features", "/internal/features/", "internal/features/"],
)
async def test_prefix_is_normalised_however_it_is_written(given: str):
    # The value comes from an env var a human types; a stray slash must
    # not produce `//internal/features` or a missing leading slash.
    reader, seen, _headers = _reader(features_path_prefix=given)
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    assert seen == [f"/internal/features/matches/{MATCH_ID}"]


@pytest.mark.parametrize("blank", ["", "   ", "/", "//"])
def test_rejects_a_blank_prefix(blank: str):
    # An empty prefix would build `/matches/{id}` and quietly query the
    # wrong route; failing at construction makes it a boot error.
    with pytest.raises(ValueError, match="prefix"):
        AnvilGatewayReader(
            base_url="http://anvil:8081", api_key=KEY, features_path_prefix=blank
        )


def test_still_rejects_a_short_api_key():
    with pytest.raises(ValueError, match="32 characters"):
        AnvilGatewayReader(base_url="http://anvil:8081", api_key="short")


# -- API key header ---------------------------------------------------- #


@pytest.mark.asyncio
async def test_defaults_to_the_gateway_api_key_header():
    reader, _seen, headers = _reader()
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    assert headers[0][DEFAULT_API_KEY_HEADER.lower()] == KEY
    assert DEFAULT_API_KEY_HEADER == "X-Atlas-Anvil-Key"


@pytest.mark.asyncio
async def test_direct_header_is_the_one_anvil_actually_checks():
    # Anvil compares `x-anvil-api-key` (anvil/runtime/health.py). Sending
    # the gateway header instead produces a 401 that is indistinguishable
    # from a wrong key — this was hit for real against the deployed
    # stack, with the correct key.
    reader, _seen, headers = _reader(api_key_header=DIRECT_API_KEY_HEADER)
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    assert headers[0]["x-anvil-api-key"] == KEY
    assert DEFAULT_API_KEY_HEADER.lower() not in headers[0]


@pytest.mark.parametrize("blank", ["", "   "])
def test_rejects_a_blank_api_key_header(blank: str):
    with pytest.raises(ValueError, match="header"):
        AnvilGatewayReader(
            base_url="http://anvil:8081", api_key=KEY, api_key_header=blank
        )


@pytest.mark.asyncio
async def test_direct_topology_sets_both_path_and_header_together():
    # The two settings are a pair: getting one right and the other wrong
    # still fails, and the failure modes (404 vs 401) look unrelated.
    reader, seen, headers = _reader(
        features_path_prefix=DIRECT_FEATURES_PATH_PREFIX,
        api_key_header=DIRECT_API_KEY_HEADER,
    )
    await reader._features(match_id=MATCH_ID, as_of=AS_OF)

    assert seen == [f"/internal/features/matches/{MATCH_ID}"]
    assert headers[0]["x-anvil-api-key"] == KEY
