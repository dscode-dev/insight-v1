"""A leitura do dataset NORMALIZADO para recuperação — podada e projetada.

DUAS OPERAÇÕES, E ELAS TÊM CUSTOS OPOSTOS:

    load_query        UMA linha, por chave. Cara em ida e volta, barata em bytes
    stream_candidates MUITAS linhas, por predicado. Barata em ida e volta,
                      cara em bytes se a projeção estiver errada

A PROJEÇÃO É O QUE DECIDE O CUSTO. O arquivo normalizado tem 330 colunas — 15
de identidade e três por eixo. Um perfil resolvido usa uma fração dos eixos, e
ler os 105 para somar sobre 14 pagaria sete vezes a leitura para descartar. O
port recebe as chaves do perfil e devolve SÓ elas, mais a identidade.

A PODA É POR PREFIXO DE CHAVE, e não por filtro depois de ler:

    normalized/{dataset}/{versão}/split=REFERENCE/competition={liga}/season=*/

`split=` e `competition=` estão no CAMINHO, então o leitor nunca abre a metade
de avaliação nem as outras ligas. O instante — `(period, minute)` — é coluna, e
vai como predicado sobre o lote lido.

    ISSO NÃO É OTIMIZAÇÃO. Um filtro em memória sobre `split` funcionaria e
    faria a correção do universo depender de um `if` em vez da estrutura do
    bucket — e um `if` esquecido produziria candidatos de avaliação com o
    ranking parecendo normal.

NENHUMA LEITURA DE FATO CANÔNICO. Este port não conhece partida, evento,
escalação, cotação nem resultado. O que ele lê é Parquet normalizado, e nada
mais — a recuperação não volta ao corpus.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.query import QuerySnapshot
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint


@runtime_checkable
class HistoricalCandidateSourcePort(Protocol):
    """A fonte de linhas normalizadas para recuperação."""

    async def load_query(
        self,
        *,
        dataset_name: str,
        version: str,
        key: HistoricalFeatureSnapshotKey,
        feature_keys: Sequence[str],
    ) -> QuerySnapshot | None:
        """A linha de AVALIAÇÃO daquela chave, ou `None`.

        `None` SIGNIFICA «NÃO EXISTE NESTE DATASET», e é diferente de «existe e
        está na referência»: a segunda é recusada pelo tipo — `QuerySnapshot`
        não aceita outra metade —, e a diferença entre as duas mensagens é o
        que separa «você digitou a chave errada» de «esta linha não é uma
        query».

        `feature_keys` VAZIO LÊ TODOS OS EIXOS. É o caso da inspeção; a
        recuperação passa os eixos do perfil resolvido e paga uma fração.
        """
        ...

    def stream_candidates(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        position: GridTimePoint,
        feature_keys: Sequence[str],
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[CandidateRow]]:
        """As linhas de REFERÊNCIA daquela competição naquele instante.

        A METADE NÃO É PARÂMETRO. Ela é sempre `REFERENCE`, e passá-la abriria
        a porta para um chamador pedir candidatos de avaliação — que é
        exatamente o vazamento que a política existe para impedir. O tipo
        `CandidateRow` recusaria a linha, e a recusa aconteceria fundo demais.

        O LOTE É DO CHAMADOR porque a pressão de memória é dele. O retriever
        não guarda os candidatos: ele mede e descarta, então o lote é o único
        termo que cresce.
        """
        ...

    async def count_candidates(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        position: GridTimePoint,
    ) -> int:
        """Quantas linhas o universo tem, SEM ler valor nenhum.

        ELE EXISTE PARA O BENCHMARK e para a inspeção. Contar lendo as linhas
        faria «qual o tamanho do universo?» custar o mesmo que responder a
        query inteira.
        """
        ...

    async def partitions(
        self, *, dataset_name: str, version: str
    ) -> Sequence[tuple[str, str, str]]:
        """As partições `(metade, competição, temporada)` que existem no bucket.

        DO OBJECT STORE, e não do banco: o que importa para a recuperação é o
        que EXISTE, e um objeto que o registro não conhece precisa aparecer.
        """
        ...
