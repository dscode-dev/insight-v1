"""O port do contexto pré-jogo — a única porta para o passado do corpus.

ELE LÊ DE UMA VERSÃO PUBLICADA, e de mais nada (§9, §40). Uma partida anterior
só conta se pertencer à MESMA `HistoricalCanonicalDatasetVersion`: existir na
tabela canônica global não basta. Duas versões do mesmo corpus podem publicar
recortes diferentes, e o contexto tem de mudar junto — senão a feature
descreveria um passado que aquela versão não publica.

A LEITURA É EM LOTE (§37, §38, §39). Uma consulta por partida — «qual foi o
jogo anterior deste time?» — daria dez mil consultas para dez mil partidas,
vezes dois times. A assinatura recebe uma SEQUÊNCIA porque é assim que ela
precisa ser usada.

DUAS PERGUNTAS, DOIS MÉTODOS, E ELES CUSTAM DIFERENTE:

    coverage()  uma vez por EXECUÇÃO — até onde a versão alcança, por
                competição. Não muda entre lotes
    load()      uma vez por LOTE — as partidas anteriores elegíveis

A separação existe porque a cobertura é propriedade da VERSÃO, e repeti-la a
cada lote seria pagar vinte vezes por uma resposta que não muda.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.prematch.models import (
    ContextCoverage,
    MatchContextInput,
)
from sports_intelligence.domain.features.prematch.policy import HistoricalContextPolicy
from sports_intelligence.domain.shared.identity import CompetitionId, MatchId


@runtime_checkable
class HistoricalContextSourcePort(Protocol):
    """O passado publicado de um conjunto de partidas."""

    async def coverage(self, version_id: str) -> Mapping[CompetitionId, ContextCoverage]:
        """Até onde a versão alcança, por competição (§32, §33).

        UMA VEZ POR EXECUÇÃO. É o instante da primeira partida publicada de
        cada competição — o que permite dizer «o corpus não chega em `T-14d`»
        em vez de afirmar zero.
        """
        ...

    async def load(
        self,
        version_id: str,
        match_ids: Sequence[MatchId],
        *,
        policy: HistoricalContextPolicy,
    ) -> Mapping[MatchId, MatchContextInput]:
        """O contexto daquelas partidas NAQUELA versão.

        `policy` ENTRA NA LEITURA, e não só no cálculo: escopo e elegibilidade
        decidem QUE LINHAS buscar — mesma competição, com resultado publicado,
        antes do apito. Aplicá-los depois exigiria trazer o passado inteiro
        para a memória e filtrar lá.

        AS PARTIDAS AUSENTES NÃO VOLTAM. Uma partida que não pertence à versão
        é diferente de uma sem histórico, e devolver um contexto vazio para as
        duas apagaria a distinção.
        """
        ...
