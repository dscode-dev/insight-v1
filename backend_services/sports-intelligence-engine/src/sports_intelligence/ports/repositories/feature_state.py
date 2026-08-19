"""O port de leitura do estado histórico — a única porta para o corpus.

ELE LÊ DE UMA VERSÃO PUBLICADA, e de mais nada (§75, §116). Não existe método
para ler arquivo bruto, execução de fusão ou registro de fonte: a ausência é o
contrato, e o teste de arquitetura a mantém.

A LEITURA É EM LOTE (§79, §81). Reconstruir dez mil estados com uma consulta
por partida — mais uma por escalação, mais uma por evento — seria o N+1 que o
motor recusa desde o PR-03. A assinatura recebe uma SEQUÊNCIA de partidas
porque é assim que ela precisa ser usada.

A LEITURA NÃO TEM OPINIÃO TEMPORAL. Ela devolve os fatos CANDIDATOS da
partida; quem projeta, filtra e decide o que era conhecível é o domínio. Uma
leitura que já filtrasse por corte precisaria conhecer a política temporal — e
duas políticas passariam a existir, uma no SQL e outra no domínio.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.state.builder import CanonicalMatchStateInput
from sports_intelligence.domain.shared.identity import MatchId


@runtime_checkable
class HistoricalMatchStateSourcePort(Protocol):
    """Os fatos publicados de um conjunto de partidas, para reconstruir estado."""

    async def load(
        self, version_id: str, match_ids: Sequence[MatchId]
    ) -> Mapping[MatchId, CanonicalMatchStateInput]:
        """Os insumos daquelas partidas NAQUELA versão.

        AS PARTIDAS AUSENTES NÃO VOLTAM, e quem chama trata a ausência: uma
        partida que não pertence à versão é diferente de uma partida sem
        eventos, e devolver um insumo vazio para as duas apagaria a distinção.
        """
        ...

    async def match_ids(
        self, version_id: str, *, limit: int = 500, after: str | None = None
    ) -> Sequence[MatchId]:
        """As partidas da versão, em páginas por chave (§80).

        `OFFSET` NÃO: percorrer dez mil linhas para descartá-las torna a
        varredura quadrática, e isso já custou uma correção no PR-03.2.
        """
        ...
