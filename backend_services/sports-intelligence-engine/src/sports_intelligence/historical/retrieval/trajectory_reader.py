"""O leitor de trajetórias — uma varredura por partição, e não por horizonte.

O NÚMERO QUE ESTE MÓDULO EXISTE PARA NÃO PRODUZIR:

    47 candidatos x 3 horizontes  =  141 leituras de Parquet por query

A partição de referência já contém as linhas dos instantes de lookback — elas
são linhas da MESMA competição, da mesma partida, alguns minutos antes. Uma
varredura da partição, retendo os quatro instantes de uma vez e agrupando por
partida, monta todas as trajetórias juntas:

    leituras de objeto   O(partições)
    linhas retidas       O(candidatos x (1 + |H|))

E A SEGUNDA LINHA É INEVITÁVEL: são as linhas que a trajetória USA. O que o
padrão N+1 acrescentaria é reabrir e decodificar o mesmo arquivo três vezes
para pegá-las.

A PROJEÇÃO É A MESMA DO PR-06.1 — identidade, digesto, e `n_`/`m_` por eixo do
perfil. O que muda é quantas LINHAS de cada objeto sobrevivem ao filtro, e não
quantas colunas são lidas.

O CONTADOR DE LINHAS É NOVO, e ele existe para o §204 e o §210: «quantas linhas
de origem uma query de trajetória lê» é o número que prova a ausência do padrão
`candidato x horizonte`, e obtê-lo depois do fato seria adivinhar.

O QUE FALTA NÃO É INVENTADO. Um instante pedido que não aparece na varredura
simplesmente não entra no mapa. Quem monta a trajetória é que decide se aquilo
é ausência estrutural — o slot estava fora do período, e o alvo nunca foi
pedido — ou corrupção; este módulo não tem contexto para essa decisão, e
adivinhá-la aqui produziria `TRAJECTORY_SOURCE_ROW_MISSING` onde deveria haver
`OUTSIDE_PERIOD_LOOKBACK`, ou o contrário.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import TrajectoryRow
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.historical.retrieval.reader import (
    IDENTITY_PROJECTION,
    _colunas,
    _colunas_presentes,
    _projecao,
    _valores_e_mascaras,
)
from sports_intelligence.ports.object_store import ObjectStorePort

_SUFIXO: Final[str] = ".parquet"

#: Quantas linhas o `iter_batches` do Arrow devolve por vez na varredura.
#:
#: ELE NÃO É O LOTE DO CHAMADOR. O lote do chamador conta CANDIDATOS montados;
#: este conta linhas cruas do Parquet, e são grandezas diferentes — um
#: candidato são `1 + |H|` linhas.
_LOTE_DE_LEITURA: Final[int] = 4_096


@final
@dataclass(frozen=True, slots=True)
class ParquetCandidateTrajectoryRows:
    """A âncora e o lookback de UM candidato, como o leitor os entrega."""

    match_id: str
    season: str
    competition: str
    anchor_key: HistoricalFeatureSnapshotKey
    anchor_position: GridTimePoint
    anchor_row_digest: str
    representation_fingerprint: str
    anchor_values: dict[str, float | None] = field(default_factory=dict)
    anchor_availabilities: dict[str, str] = field(default_factory=dict)
    lookback: dict[GridTimePoint, TrajectoryRow] = field(default_factory=dict)


@final
class ParquetHistoricalTrajectorySource:
    """Lê âncora e lookback do object store, numa varredura por partição."""

    __slots__ = ("_bytes_lidos", "_linhas_lidas", "_objetos_lidos", "_store")

    def __init__(self, store: ObjectStorePort) -> None:
        self._store = store
        self._objetos_lidos = 0
        self._bytes_lidos = 0
        self._linhas_lidas = 0

    # ---------------------------------------------------- a instrumentação --

    @property
    def objects_read(self) -> int:
        return self._objetos_lidos

    @property
    def bytes_read(self) -> int:
        return self._bytes_lidos

    @property
    def source_rows_read(self) -> int:
        """Quantas linhas de origem foram RETIDAS pelo filtro de instante.

        ELE PROVA A AUSÊNCIA DO N+1 (§210). Com uma varredura por partição, a
        razão entre linhas retidas e objetos lidos é `candidatos x (1 + |H|)`
        por partição; com o padrão N+1, os objetos cresceriam junto.
        """
        return self._linhas_lidas

    def reset_counters(self) -> None:
        self._objetos_lidos = 0
        self._bytes_lidos = 0
        self._linhas_lidas = 0

    # ------------------------------------------------------------- a query --

    async def load_query_trajectory_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        key: HistoricalFeatureSnapshotKey,
        targets: Sequence[GridTimePoint],
        feature_keys: Sequence[str],
    ) -> dict[GridTimePoint, TrajectoryRow]:
        """As linhas de lookback da partida da query — UMA varredura.

        ELA VARRE A METADE DE AVALIAÇÃO, como `load_query` do PR-06.1 e pelo
        mesmo motivo: a chave é `(partida, corte)` e o caminho não carrega a
        partida. A diferença é que ela retém `|H|` linhas em vez de uma — e a
        varredura é a MESMA.
        """
        import pyarrow.parquet as pq

        if not targets:
            return {}
        procurados = set(targets)
        colunas = _projecao(feature_keys)
        encontradas: dict[GridTimePoint, TrajectoryRow] = {}
        for chave in await self._objetos(
            dataset_name=dataset_name, version=version, split=DatasetSplit.EVALUATION
        ):
            bruto = await self._baixar(chave)
            arquivo = pq.ParquetFile(io.BytesIO(bruto))
            presentes = _colunas_presentes(arquivo.schema_arrow.names, colunas)
            for lote in arquivo.iter_batches(batch_size=_LOTE_DE_LEITURA, columns=presentes):
                self._coletar(
                    lote,
                    feature_keys=feature_keys,
                    match_key=key.match_key,
                    targets=procurados,
                    destino=encontradas,
                )
            if len(encontradas) == len(procurados):
                # TODOS OS INSTANTES JÁ VIERAM. Isto NÃO é poda por distância
                # nem parada antecipada de ranking: é parar de procurar o que
                # já foi encontrado, e as linhas de uma partida vivem todas na
                # mesma partição.
                break
        return encontradas

    # ------------------------------------------------------- os candidatos --

    async def stream_candidate_trajectories(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        anchor: GridTimePoint,
        targets: Sequence[GridTimePoint],
        feature_keys: Sequence[str],
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[ParquetCandidateTrajectoryRows]]:
        """Âncora e lookback de cada candidato, agrupados por partida.

        A VARREDURA É POR PARTIÇÃO, e o agrupamento acontece DENTRO dela: as
        linhas de uma partida — âncora e lookback — vivem todas no mesmo
        objeto, porque a partição é `(metade, competição, temporada)` e a
        partida não a atravessa.
        """
        if batch_rows < 1:
            raise ValidationError(f"lote de {batch_rows} candidatos: ele precisa ser >= 1")
        import pyarrow.parquet as pq

        instantes = {anchor, *targets}
        colunas = _projecao(feature_keys)
        for chave in await self._objetos(
            dataset_name=dataset_name,
            version=version,
            split=DatasetSplit.REFERENCE,
            competition=competition,
        ):
            bruto = await self._baixar(chave)
            arquivo = pq.ParquetFile(io.BytesIO(bruto))
            presentes = _colunas_presentes(arquivo.schema_arrow.names, colunas)
            por_partida: dict[str, _EmMontagem] = {}
            for lote in arquivo.iter_batches(batch_size=_LOTE_DE_LEITURA, columns=presentes):
                self._agrupar(
                    lote,
                    feature_keys=feature_keys,
                    anchor=anchor,
                    instantes=instantes,
                    destino=por_partida,
                )
            lote_montado: list[ParquetCandidateTrajectoryRows] = []
            for partida in sorted(por_partida):
                montado = por_partida[partida].finalizar()
                if montado is None:
                    # SEM ÂNCORA, NÃO HÁ CANDIDATO. Uma partida que tem
                    # lookback e não tem a linha do instante da query
                    # simplesmente não está no universo daquele instante —
                    # o PR-06.1 já a excluiria pelo predicado.
                    continue
                lote_montado.append(montado)
                if len(lote_montado) >= batch_rows:
                    yield lote_montado
                    lote_montado = []
            if lote_montado:
                yield lote_montado

    async def count_trajectory_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        targets: Sequence[GridTimePoint],
    ) -> int:
        """As linhas dos instantes pedidos, lendo só as duas colunas do tempo."""
        import pyarrow.parquet as pq

        procurados = set(targets)
        total = 0
        for chave in await self._objetos(
            dataset_name=dataset_name,
            version=version,
            split=DatasetSplit.REFERENCE,
            competition=competition,
        ):
            bruto = await self._baixar(chave)
            tabela = pq.read_table(io.BytesIO(bruto), columns=["period", "minute"])
            fases = tabela.column("period").to_pylist()
            minutos = tabela.column("minute").to_pylist()
            total += sum(
                1
                for fase, minuto in zip(fases, minutos, strict=True)
                if GridTimePoint.from_columns(period=str(fase), minute=int(minuto)) in procurados
            )
        return total

    # ------------------------------------------------------------- interno --

    def _coletar(
        self,
        lote: Any,
        *,
        feature_keys: Sequence[str],
        match_key: str,
        targets: set[GridTimePoint],
        destino: dict[GridTimePoint, TrajectoryRow],
    ) -> None:
        """As linhas DAQUELA partida nos instantes pedidos."""
        colunas = _colunas(lote, [*IDENTITY_PROJECTION, *_colunas_de_eixo(feature_keys)])
        partidas = colunas.get("match_id", [])
        for indice, partida in enumerate(partidas):
            if str(partida) != match_key:
                continue
            posicao = GridTimePoint.from_columns(
                period=str(colunas["period"][indice]),
                minute=int(colunas["minute"][indice]),
            )
            if posicao not in targets or posicao in destino:
                continue
            valores, mascaras = _valores_e_mascaras(colunas, feature_keys, indice)
            self._linhas_lidas += 1
            destino[posicao] = TrajectoryRow(
                key=HistoricalFeatureSnapshotKey(
                    match_key=str(partida),
                    grid_index=int(colunas["grid_index"][indice]),
                ),
                position=posicao,
                row_digest=str(colunas["row_digest"][indice]),
                values=valores,
                availabilities=mascaras,
            )

    def _agrupar(
        self,
        lote: Any,
        *,
        feature_keys: Sequence[str],
        anchor: GridTimePoint,
        instantes: set[GridTimePoint],
        destino: dict[str, _EmMontagem],
    ) -> None:
        """As linhas dos instantes pedidos, indexadas por partida."""
        colunas = _colunas(lote, [*IDENTITY_PROJECTION, *_colunas_de_eixo(feature_keys)])
        partidas = colunas.get("match_id", [])
        for indice, partida in enumerate(partidas):
            posicao = GridTimePoint.from_columns(
                period=str(colunas["period"][indice]),
                minute=int(colunas["minute"][indice]),
            )
            if posicao not in instantes:
                continue
            self._linhas_lidas += 1
            chave = str(partida)
            montagem = destino.setdefault(
                chave,
                _EmMontagem(
                    match_id=chave,
                    season=str(colunas["season"][indice]),
                    competition=str(colunas["competition"][indice]),
                    anchor=anchor,
                ),
            )
            valores, mascaras = _valores_e_mascaras(colunas, feature_keys, indice)
            linha = TrajectoryRow(
                key=HistoricalFeatureSnapshotKey(
                    match_key=chave, grid_index=int(colunas["grid_index"][indice])
                ),
                position=posicao,
                row_digest=str(colunas["row_digest"][indice]),
                values=valores,
                availabilities=mascaras,
            )
            if posicao == anchor:
                montagem.ancora = linha
                montagem.representation_fingerprint = str(
                    colunas["representation_fingerprint"][indice]
                )
            else:
                montagem.lookback[posicao] = linha

    async def _objetos(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit,
        competition: str | None = None,
    ) -> list[str]:
        """As chaves de Parquet sob o prefixo podado, ORDENADAS."""
        prefixo = f"normalized/{dataset_name}/{version}/split={split.value}/"
        if competition is not None:
            prefixo += f"competition={competition}/"
        return sorted(
            [chave async for chave in self._store.list_prefix(prefixo) if chave.endswith(_SUFIXO)]
        )

    async def _baixar(self, chave: str) -> bytes:
        buffer = bytearray()
        async for bloco in self._store.open_stream(chave):
            buffer.extend(bloco)
        self._objetos_lidos += 1
        self._bytes_lidos += len(buffer)
        return bytes(buffer)


@final
@dataclass(slots=True)
class _EmMontagem:
    """Uma partida sendo montada durante a varredura da partição."""

    match_id: str
    season: str
    competition: str
    anchor: GridTimePoint
    ancora: TrajectoryRow | None = None
    representation_fingerprint: str = ""
    lookback: dict[GridTimePoint, TrajectoryRow] = field(default_factory=dict)

    def finalizar(self) -> ParquetCandidateTrajectoryRows | None:
        if self.ancora is None:
            return None
        return ParquetCandidateTrajectoryRows(
            match_id=self.match_id,
            season=self.season,
            competition=self.competition,
            anchor_key=self.ancora.key,
            anchor_position=self.ancora.position,
            anchor_row_digest=self.ancora.row_digest,
            representation_fingerprint=self.representation_fingerprint,
            anchor_values=dict(self.ancora.values),
            anchor_availabilities=dict(self.ancora.availabilities),
            lookback=dict(self.lookback),
        )


def _colunas_de_eixo(feature_keys: Sequence[str]) -> list[str]:
    """As colunas de valor e de máscara dos eixos — sem a identidade."""
    from sports_intelligence.historical.normalized.materializer import (
        MASK_PREFIX,
        NORMALIZED_PREFIX,
    )

    nomes: list[str] = []
    for chave in feature_keys:
        nomes.append(f"{NORMALIZED_PREFIX}{chave}")
        nomes.append(f"{MASK_PREFIX}{chave}")
    return nomes


def trajectory_source_summary(
    source: ParquetHistoricalTrajectorySource,
) -> Mapping[str, int]:
    """Os contadores, para o benchmark e para o relatório."""
    return {
        "bytes_read": source.bytes_read,
        "objects_read": source.objects_read,
        "source_rows_read": source.source_rows_read,
    }
