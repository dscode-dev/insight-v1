"""A leitura de TRAJETÓRIAS — âncora e lookback na MESMA varredura.

O PADRÃO QUE ESTE PORT EXISTE PARA IMPEDIR (§127, §245):

    para cada candidato:
        ler t-1
        ler t-3
        ler t-5

Isso é `O(candidatos x |H|)` leituras. Com quarenta e sete candidatos e três
horizontes, cento e quarenta e uma idas ao object store para responder UMA
query — e cada ida abre e decodifica um Parquet inteiro.

A FORMA CERTA É A OPOSTA, e ela cabe numa frase: a partição de referência já
contém TODAS as linhas daquela competição, inclusive as dos instantes de
lookback. Uma varredura da partição, filtrando os QUATRO instantes de uma vez e
agrupando por partida, monta todas as trajetórias juntas.

    leituras   O(partições)
    linhas     O(candidatos x (1 + |H|))     inevitável: são as linhas
    bytes      os mesmos de uma varredura de estado, com mais linhas
               retidas do MESMO arquivo

    §129 pede exatamente isso: `O(partições / lotes)`, e não
    `O(candidatos x horizontes)`.

A PROJEÇÃO NÃO REGRIDE (§131, §132). As mesmas colunas do PR-06.1 — identidade,
digesto, e `n_`/`m_` por eixo do perfil. O que muda é QUANTAS LINHAS de cada
objeto são retidas, e não quantas colunas.

A PODA TAMBÉM NÃO (§133). `split=` e `competition=` continuam no caminho, e o
conjunto de instantes vai como predicado sobre o lote lido.

E O FUTURO NÃO É PEDIDO. O port recebe os instantes-alvo já resolvidos pela
`TrajectoryWindowPolicy`, e essa política só produz lookback dentro do mesmo
período. Não há parâmetro por onde pedir `t + h`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import TrajectoryRow


@runtime_checkable
class HistoricalTrajectorySourcePort(Protocol):
    """A fonte de linhas de âncora e de lookback, em lote."""

    async def load_query_trajectory_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        key: HistoricalFeatureSnapshotKey,
        targets: Sequence[GridTimePoint],
        feature_keys: Sequence[str],
    ) -> dict[GridTimePoint, TrajectoryRow]:
        """As linhas de lookback DA PARTIDA DA QUERY, indexadas por instante.

        UMA VARREDURA, e não uma por horizonte (§130). A metade de avaliação é
        percorrida uma vez, retendo as linhas daquela partida nos instantes
        pedidos.

        O QUE FALTA NÃO É INVENTADO. Um instante pedido que não aparece sai do
        mapa, e quem monta a trajetória decide o que isso significa — ausência
        estrutural ou corrupção. Este port não tem contexto para essa decisão.
        """
        ...

    def stream_candidate_trajectories(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        anchor: GridTimePoint,
        targets: Sequence[GridTimePoint],
        feature_keys: Sequence[str],
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[CandidateTrajectoryRows]]:
        """Âncora e lookback de cada candidato, agrupados por PARTIDA.

        A METADE NÃO É PARÂMETRO — ela é sempre `REFERENCE`, pelo mesmo motivo
        do port de estado: passá-la abriria a porta para candidatos de
        avaliação.

        O AGRUPAMENTO É POR PARTIDA porque a trajetória é o movimento DAQUELA
        partida. Duas partidas com o mesmo instante de âncora são dois
        candidatos, e misturar as linhas delas produziria deslocamentos entre
        jogos diferentes.
        """
        ...

    async def count_trajectory_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        targets: Sequence[GridTimePoint],
    ) -> int:
        """Quantas linhas os instantes pedidos somam, SEM ler valor nenhum.

        ELE EXISTE PARA O BENCHMARK (§204): «quantas linhas de origem uma query
        de trajetória lê» é um número que precisa ser reportado, e obtê-lo
        rodando a recuperação faria o diagnóstico custar o resultado.
        """
        ...


class CandidateTrajectoryRows(Protocol):
    """A âncora e o lookback de UM candidato, como o leitor os entrega."""

    @property
    def match_id(self) -> str: ...

    @property
    def season(self) -> str: ...

    @property
    def competition(self) -> str: ...

    @property
    def anchor_key(self) -> HistoricalFeatureSnapshotKey: ...

    @property
    def anchor_position(self) -> GridTimePoint: ...

    @property
    def anchor_row_digest(self) -> str: ...

    @property
    def anchor_values(self) -> dict[str, float | None]: ...

    @property
    def anchor_availabilities(self) -> dict[str, str]: ...

    @property
    def representation_fingerprint(self) -> str: ...

    @property
    def lookback(self) -> dict[GridTimePoint, TrajectoryRow]: ...
