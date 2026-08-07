"""Historical enrichment from ClickHouse — reachable only from the resenha flows.

    Anvil /internal/features/historical/*  →  THIS  →  pre/post-match resenhas

THE RULE THIS ENFORCES, as the platform owner stated it:

    "O Atlas só vai consumir esses dados históricos persistidos no Clickhouse
     somente para criação de contexto e tendências (que virarão posts) para os
     fluxos de resenhas pré/pós-jogos. Os jogos ao vivos e suas postagens devem
     ser influenciadas totalmente pelo os dados (vetores) que vamos persistir no
     postgres (pgvector), pois consideramos essa camada de hot path."

WHAT THE RULE IS NOT. It does not say the resenha reads ClickHouse INSTEAD of
pgvector. A resenha reads the vectors like everything else and adds history on
top where the extra depth is worth it:

    ao vivo   →  pgvector
    resenha   →  pgvector  +  ClickHouse

So nothing here removes a vector read from any path. This client only adds a
second source, and only where the flow permits one.

WHY A GATE IN CODE RATHER THAN A CONVENTION. The two stores answer different
questions and a caller cannot feel the difference: a baseline from ClickHouse
and a neighbour from pgvector both arrive as numbers in a report. What
separates them is latency and freshness — an HTTP round trip to an analytical
store, against an indexed lookup in the database Atlas already holds open. A
live match is the one moment that cannot absorb the former, and it is also the
moment when the temptation to reach for "just one baseline" is highest,
because the live path is where a comparison feels most useful.

An `AnalysisFlow` that every call must name makes reaching across the boundary
something you have to write down, and something a test can see.
"""

from __future__ import annotations

import enum
from typing import Any
from urllib.parse import quote

import httpx


class AnalysisFlow(str, enum.Enum):
    """Which flow is asking. Named at the call site, never inferred.

    Inferring it — from whether a match has finished, say — would put the
    boundary at the mercy of a clock and a status field, and a late status
    update would silently open the cold path to a live match.
    """

    LIVE = "live"
    PRE_MATCH = "pre_match"
    POST_MATCH = "post_match"


#: The flows a resenha runs in. Both are composed ahead of publication, with
#: no match in progress waiting on the answer.
COLD_PATH_FLOWS = frozenset({AnalysisFlow.PRE_MATCH, AnalysisFlow.POST_MATCH})


class ColdPathNotAvailable(RuntimeError):
    """Raised when the live flow asks for historical enrichment.

    Deliberately not a silent empty result: returning `{}` would let a live
    caller keep the call in place and read the absence as "no history for this
    team", which is a different and wrong statement.
    """


class AnvilHistoricalError(Exception):
    pass


class HistoricalEnrichmentReader:
    """Reads the historical baselines Anvil computes over ClickHouse.

    Teams are addressed by `club_id`. The raw name is what a source happened
    to write — `Barcelona`, `FC Barcelona` — and filtering on it answers from
    whichever spelling matches, with a sample_size that looks plausible.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        path_prefix: str = "/internal/features/historical",
    ) -> None:
        self._client = client
        self._prefix = "/" + path_prefix.strip().strip("/")

    async def aclose(self) -> None:
        await self._client.aclose()

    def available_for(self, flow: AnalysisFlow) -> bool:
        """Lets a caller compose a report without catching an exception to
        find out whether the section it is about to build is permitted."""
        return flow in COLD_PATH_FLOWS

    async def team_baseline(
        self, *, flow: AnalysisFlow, club_id: str, competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._get(flow, "team", {
            "club_id": club_id, "competition_key": competition_key,
            "seasons": seasons or [],
        })

    async def team_stats_baseline(
        self, *, flow: AnalysisFlow, club_id: str, competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._get(flow, "team-stats", {
            "club_id": club_id, "competition_key": competition_key,
            "seasons": seasons or [],
        })

    async def head_to_head(
        self, *, flow: AnalysisFlow, home_club_id: str, away_club_id: str,
        competition_key: str | None = None, limit: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "home_club_id": home_club_id,
            "away_club_id": away_club_id,
            "limit": limit,
        }
        if competition_key:
            params["competition_key"] = competition_key
        return await self._get(flow, "head-to-head", params)

    async def market_baseline(
        self, *, flow: AnalysisFlow, competition_key: str,
        seasons: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._get(flow, "market", {
            "competition_key": competition_key, "seasons": seasons or [],
        })

    async def coverage(self, *, flow: AnalysisFlow) -> dict[str, Any]:
        return await self._get(flow, "coverage", {})

    async def _get(
        self, flow: AnalysisFlow, kind: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        # The single choke point. Every public method above routes through it,
        # so a method added later cannot forget the check by omission — it
        # would have to reimplement the request to get around it.
        if flow not in COLD_PATH_FLOWS:
            raise ColdPathNotAvailable(
                f"fluxo {flow.value} nao consulta o ClickHouse: o caminho quente "
                "le apenas os vetores no pgvector"
            )

        path = f"{self._prefix}/{quote(kind, safe='')}"
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise AnvilHistoricalError(str(exc)) from exc
        if response.status_code >= 400:
            raise AnvilHistoricalError(
                f"http_{response.status_code}: {response.text[:200]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise AnvilHistoricalError("resposta historica invalida")
        return payload
