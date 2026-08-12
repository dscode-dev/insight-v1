"""Séries temporais de alto volume: eventos, snapshots, ticks de odds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AnalyticsStorePort(Protocol):
    """ClickHouse, visto pelo domínio como append e leitura por partida.

    SEM UPDATE. Este armazenamento é append-only por contrato (ADR-0005): um
    snapshot corrigido é uma linha NOVA com versão maior, e a linha antiga
    permanece como registro do que se sabia antes. Sem isso, "por que o motor
    disse aquilo" deixa de ter resposta.
    """

    async def append(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None: ...

    async def query(
        self, statement: str, parameters: Mapping[str, Any]
    ) -> Sequence[Mapping[str, Any]]:
        """Consulta parametrizada. Parâmetros separados do texto, sempre:
        interpolar valor em SQL é injeção mesmo quando a fonte é interna."""
        ...
