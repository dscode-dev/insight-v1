"""The live flow reads vectors; only a resenha may also read ClickHouse.

    ao vivo   ->  pgvector
    resenha   ->  pgvector  +  ClickHouse

The second line is the one people misread. The rule does not move a resenha
off the vectors — it lets a resenha add history on top, because it is composed
ahead of publication and can afford the round trip. A live match cannot.
"""

from __future__ import annotations

import ast
import pathlib

import httpx
import pytest

from atlas.clients.anvil_historical import (
    COLD_PATH_FLOWS,
    AnalysisFlow,
    ColdPathNotAvailable,
    HistoricalEnrichmentReader,
)


def _reader(handler=None) -> HistoricalEnrichmentReader:
    def _ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sample_size": 3, "url": str(request.url)})

    transport = httpx.MockTransport(handler or _ok)
    return HistoricalEnrichmentReader(
        httpx.AsyncClient(transport=transport, base_url="http://anvil")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", sorted(COLD_PATH_FLOWS, key=lambda f: f.value))
async def test_resenha_flows_may_enrich_from_clickhouse(flow):
    reader = _reader()
    result = await reader.team_baseline(
        flow=flow, club_id="barcelona", competition_key="la_liga"
    )
    assert result["sample_size"] == 3


@pytest.mark.asyncio
async def test_live_flow_is_refused():
    reader = _reader()
    with pytest.raises(ColdPathNotAvailable):
        await reader.team_baseline(
            flow=AnalysisFlow.LIVE, club_id="barcelona", competition_key="la_liga"
        )


@pytest.mark.asyncio
async def test_the_refusal_is_not_an_empty_result():
    """`{}` would let a live caller leave the call in place and read the
    absence as "this team has no history", which is a different claim."""
    reader = _reader()
    for call in (
        lambda: reader.head_to_head(
            flow=AnalysisFlow.LIVE, home_club_id="a", away_club_id="b"),
        lambda: reader.market_baseline(
            flow=AnalysisFlow.LIVE, competition_key="la_liga"),
        lambda: reader.team_stats_baseline(
            flow=AnalysisFlow.LIVE, club_id="a", competition_key="la_liga"),
        lambda: reader.coverage(flow=AnalysisFlow.LIVE),
    ):
        with pytest.raises(ColdPathNotAvailable):
            await call()


@pytest.mark.asyncio
async def test_no_request_leaves_the_process_on_a_live_call():
    """The gate has to precede the round trip, not discard its result — the
    cost being avoided is the latency, not the bytes."""
    calls: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    reader = _reader(record)
    with pytest.raises(ColdPathNotAvailable):
        await reader.team_baseline(
            flow=AnalysisFlow.LIVE, club_id="x", competition_key="y"
        )
    assert calls == []


@pytest.mark.asyncio
async def test_available_for_lets_a_caller_ask_before_composing():
    reader = _reader()
    assert reader.available_for(AnalysisFlow.PRE_MATCH)
    assert reader.available_for(AnalysisFlow.POST_MATCH)
    assert not reader.available_for(AnalysisFlow.LIVE)


@pytest.mark.asyncio
async def test_teams_are_addressed_by_club_id():
    """`Barcelona` and `FC Barcelona` are the same club to everyone except a
    string comparison, which is what the query used to be."""
    seen: list[httpx.URL] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={})

    reader = _reader(record)
    await reader.head_to_head(
        flow=AnalysisFlow.PRE_MATCH, home_club_id="barcelona",
        away_club_id="real_betis",
    )
    query = str(seen[0])
    assert "home_club_id=barcelona" in query
    assert "away_club_id=real_betis" in query


def test_every_public_method_routes_through_the_gate():
    """A method added later must not be able to skip the check by omission.

    Read from the AST rather than by calling each one: a new method is
    precisely the case a hand-written list of methods would miss.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "atlas" / "clients" / "anvil_historical.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    reader = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "HistoricalEnrichmentReader"
    )
    exempt = {"__init__", "aclose", "available_for", "_get"}
    public = [
        node for node in reader.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name not in exempt
    ]
    assert public, "nenhum metodo de leitura encontrado"

    for method in public:
        calls_gate = any(
            isinstance(node, ast.Attribute) and node.attr == "_get"
            for node in ast.walk(method)
        )
        assert calls_gate, f"{method.name} nao passa por _get — o gate e' la'"

        takes_flow = any(
            arg.arg == "flow" for arg in method.args.kwonlyargs
        )
        assert takes_flow, f"{method.name} precisa receber flow explicitamente"
