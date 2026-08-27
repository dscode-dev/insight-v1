"""A leitura do dataset normalizado para recuperação, em Parquet.

TRÊS ECONOMIAS, E AS TRÊS SÃO DO FORMATO COLUNAR:

    poda de partição   `split=REFERENCE/competition={liga}/` está no CAMINHO, e
                       o leitor nunca abre a avaliação nem as outras ligas
    projeção           15 colunas de identidade mais duas por eixo do perfil.
                       Um perfil de 14 eixos lê 43 colunas de 330
    predicado          `(period, minute)` filtra o lote lido, e o `row_digest`
                       de quem não passa nunca é materializado

O PREDICADO TEMPORAL É APLICADO SOBRE O LOTE, e não empurrado para o Parquet.
A razão é o layout: o arquivo é ordenado por `(match_key, grid_index)`, e as
linhas de um mesmo minuto ficam espalhadas por todas as partidas — um filtro de
grupo de linhas não poda nada. O que ele evita é a construção dos objetos, que
é onde o custo está.

    MEDIR ANTES DE OTIMIZAR. Se o benchmark mostrar que a leitura domina, a
    saída é reparticionar o dataset por instante — e isso é uma decisão de
    layout do PR-06.4, não um `if` aqui.

DUAS COLUNAS POR EIXO, E NÃO TRÊS. O arquivo tem `n_` (valor), `m_` (por que a
normalização não produziu número) e `s_` (por que o valor cru não existia). A
recuperação precisa das duas primeiras: a terceira explica a CAUSA da ausência,
e a causa não muda a elegibilidade sob caso completo. Ela volta no PR-06.2,
onde a distância vai precisar distinguir os motivos.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Sequence
from typing import Any, Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.query import QuerySnapshot
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.historical.normalized.materializer import (
    MASK_PREFIX,
    NORMALIZED_PREFIX,
)
from sports_intelligence.ports.object_store import ObjectStorePort

#: As colunas de identidade que toda leitura precisa. Quinze de trezentas e
#: trinta — e `season` entra porque o vizinho a reporta.
IDENTITY_PROJECTION: Final[tuple[str, ...]] = (
    "match_id",
    "grid_index",
    "period",
    "minute",
    "split",
    "competition",
    "season",
    "row_digest",
    "representation_fingerprint",
    "plan_fingerprint",
    "artifact_set_fingerprint",
)

_SUFIXO: Final[str] = ".parquet"


@final
class ParquetHistoricalCandidateSource:
    """Lê linhas normalizadas do object store, podadas e projetadas."""

    __slots__ = ("_bytes_lidos", "_objetos_lidos", "_store")

    def __init__(self, store: ObjectStorePort) -> None:
        self._store = store
        # A INSTRUMENTAÇÃO É PÚBLICA, e não de teste. «Quantos bytes uma query
        # custou» é pergunta de baseline, e sem estes contadores ela só se
        # responde acoplando um profiler ao processo.
        self._objetos_lidos = 0
        self._bytes_lidos = 0

    @property
    def objects_read(self) -> int:
        return self._objetos_lidos

    @property
    def bytes_read(self) -> int:
        return self._bytes_lidos

    def reset_counters(self) -> None:
        self._objetos_lidos = 0
        self._bytes_lidos = 0

    # ------------------------------------------------------------ a query --

    async def load_query(
        self,
        *,
        dataset_name: str,
        version: str,
        key: HistoricalFeatureSnapshotKey,
        feature_keys: Sequence[str],
    ) -> QuerySnapshot | None:
        """A linha de AVALIAÇÃO daquela chave.

        ELA VARRE A METADE DE AVALIAÇÃO INTEIRA no pior caso, e isso é aceito:
        a chave é `(match_key, grid_index)` e o caminho não carrega a partida,
        então não há prefixo que a alcance. O custo é de UMA query, e o
        alternativo — um índice de chave para objeto — é persistência nova que
        o §79 não autoriza sem necessidade demonstrada.
        """
        import pyarrow.parquet as pq

        colunas = _projecao(feature_keys)
        for chave in await self._objetos(
            dataset_name=dataset_name, version=version, split=DatasetSplit.EVALUATION
        ):
            bruto = await self._baixar(chave)
            arquivo = pq.ParquetFile(io.BytesIO(bruto))
            presentes = _colunas_presentes(arquivo.schema_arrow.names, colunas)
            for lote in arquivo.iter_batches(batch_size=4_096, columns=presentes):
                linha = _achar(lote, key, feature_keys)
                if linha is not None:
                    return linha
        return None

    # -------------------------------------------------------- os candidatos --

    async def stream_candidates(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        position: GridTimePoint,
        feature_keys: Sequence[str],
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[CandidateRow]]:
        """As linhas de REFERÊNCIA daquela competição naquele instante."""
        if batch_rows < 1:
            raise ValidationError(f"lote de {batch_rows} linhas: ele precisa ser >= 1")
        import pyarrow.parquet as pq

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
            for lote in arquivo.iter_batches(batch_size=batch_rows, columns=presentes):
                candidatos = _para_candidatos(lote, feature_keys, position)
                if candidatos:
                    yield candidatos

    async def count_candidates(
        self,
        *,
        dataset_name: str,
        version: str,
        competition: str,
        position: GridTimePoint,
    ) -> int:
        """A contagem do universo, lendo só as duas colunas do instante."""
        import pyarrow.parquet as pq

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
                if GridTimePoint.from_columns(period=str(fase), minute=int(minuto)).aligns_with(
                    position
                )
            )
        return total

    async def partitions(
        self, *, dataset_name: str, version: str
    ) -> Sequence[tuple[str, str, str]]:
        vistas: set[tuple[str, str, str]] = set()
        for chave in await self._objetos(dataset_name=dataset_name, version=version):
            vistas.add(_particao_da_chave(chave))
        return sorted(vistas)

    # ------------------------------------------------------------- interno --

    async def _objetos(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
        competition: str | None = None,
    ) -> list[str]:
        """As chaves de Parquet sob o prefixo podado, ORDENADAS.

        A PODA É POR PREFIXO, e a ordem de montagem dele é a do caminho:
        `split=` antes de `competition=`. Pedir competição sem metade não faz
        sentido no layout, e a assinatura permite — porque `partitions()` pede
        os dois em branco.
        """
        prefixo = f"normalized/{dataset_name}/{version}/"
        if split is not None:
            prefixo += f"split={split.value}/"
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


# =============================================================== projeção ==


def _projecao(feature_keys: Sequence[str]) -> list[str]:
    """Identidade sempre; duas colunas por eixo do perfil.

    `feature_keys` VAZIO LÊ SÓ A IDENTIDADE, e não «tudo»: quem não passa eixos
    está inspecionando o dataset, e trazer 315 colunas por engano seria o
    oposto do que o port promete.
    """
    colunas = list(IDENTITY_PROJECTION)
    for chave in feature_keys:
        colunas.append(f"{NORMALIZED_PREFIX}{chave}")
        colunas.append(f"{MASK_PREFIX}{chave}")
    return colunas


def _colunas_presentes(disponiveis: Sequence[str], pedidas: Sequence[str]) -> list[str]:
    """As colunas pedidas que o arquivo tem.

    UM EIXO PEDIDO E AUSENTE NÃO É ERRO AQUI. O perfil foi resolvido sobre o
    plano do dataset, e uma coluna faltando significa que o dataset foi
    construído sob outro plano — quem confere isso é o caso de uso, com as
    impressões, e a mensagem dele fala de plano em vez de coluna.
    """
    conjunto = set(disponiveis)
    return [nome for nome in pedidas if nome in conjunto]


def _particao_da_chave(chave: str) -> tuple[str, str, str]:
    partes = {
        pedaco.split("=", 1)[0]: pedaco.split("=", 1)[1]
        for pedaco in chave.split("/")
        if "=" in pedaco
    }
    faltando = [c for c in ("split", "competition", "season") if c not in partes]
    if faltando:
        raise ValidationError(
            f"a chave {chave!r} não declara {faltando}: um objeto fora do esquema de "
            "partição é invisível para toda leitura que poda por prefixo",
            context={"object_key": chave},
        )
    return (partes["split"], partes["competition"], partes["season"])


# ============================================================== conversão ==


def _colunas(lote: Any, nomes: Sequence[str]) -> dict[str, list[Any]]:
    """As colunas do lote em listas Python, uma travessia por COLUNA.

    `to_pylist()` POR COLUNA, e não por célula: a travessia de Arrow para
    Python custa por chamada, e fazê-la por célula multiplicaria o custo pelo
    número de linhas.
    """
    presentes = set(lote.schema.names)
    return {nome: lote.column(nome).to_pylist() for nome in nomes if nome in presentes}


def _valores_e_mascaras(
    colunas: dict[str, list[Any]], feature_keys: Sequence[str], indice: int
) -> tuple[dict[str, float | None], dict[str, str]]:
    valores: dict[str, float | None] = {}
    mascaras: dict[str, str] = {}
    for chave in feature_keys:
        coluna_valor = colunas.get(f"{NORMALIZED_PREFIX}{chave}")
        coluna_mascara = colunas.get(f"{MASK_PREFIX}{chave}")
        bruto = None if coluna_valor is None else coluna_valor[indice]
        valores[chave] = None if bruto is None else float(bruto)
        mascaras[chave] = "" if coluna_mascara is None else str(coluna_mascara[indice])
    return valores, mascaras


def _para_candidatos(
    lote: Any, feature_keys: Sequence[str], position: GridTimePoint
) -> list[CandidateRow]:
    """O lote filtrado pelo instante e convertido em candidatos.

    O FILTRO VEM ANTES DA CONSTRUÇÃO. Construir todos e descartar depois
    pagaria a materialização de noventa e uma linhas por partida para ficar com
    uma — e a materialização é onde o custo está.
    """
    colunas = _colunas(lote, _projecao(feature_keys))
    fases = colunas.get("period", [])
    minutos = colunas.get("minute", [])
    linhas: list[CandidateRow] = []
    for indice in range(lote.num_rows):
        posicao = GridTimePoint.from_columns(period=str(fases[indice]), minute=int(minutos[indice]))
        if not posicao.aligns_with(position):
            continue
        valores, mascaras = _valores_e_mascaras(colunas, feature_keys, indice)
        linhas.append(
            CandidateRow(
                key=HistoricalFeatureSnapshotKey(
                    match_key=str(colunas["match_id"][indice]),
                    grid_index=int(colunas["grid_index"][indice]),
                ),
                split=DatasetSplit(colunas["split"][indice]),
                match_id=str(colunas["match_id"][indice]),
                competition=str(colunas["competition"][indice]),
                season=str(colunas["season"][indice]),
                position=posicao,
                row_digest=str(colunas["row_digest"][indice]),
                representation_fingerprint=str(colunas["representation_fingerprint"][indice]),
                values=valores,
                availabilities=mascaras,
            )
        )
    return linhas


def _achar(
    lote: Any, key: HistoricalFeatureSnapshotKey, feature_keys: Sequence[str]
) -> QuerySnapshot | None:
    """A linha daquela chave dentro do lote, ou `None`."""
    colunas = _colunas(lote, _projecao(feature_keys))
    partidas = colunas.get("match_id", [])
    indices = colunas.get("grid_index", [])
    for indice in range(lote.num_rows):
        if str(partidas[indice]) != key.match_key or int(indices[indice]) != key.grid_index:
            continue
        valores, mascaras = _valores_e_mascaras(colunas, feature_keys, indice)
        return QuerySnapshot(
            key=key,
            split=DatasetSplit(colunas["split"][indice]),
            competition=str(colunas["competition"][indice]),
            season=str(colunas["season"][indice]),
            position=GridTimePoint.from_columns(
                period=str(colunas["period"][indice]),
                minute=int(colunas["minute"][indice]),
            ),
            row_digest=str(colunas["row_digest"][indice]),
            representation_fingerprint=str(colunas["representation_fingerprint"][indice]),
            plan_fingerprint=str(colunas["plan_fingerprint"][indice]),
            artifact_set_fingerprint=str(colunas["artifact_set_fingerprint"][indice]),
            values=valores,
            availabilities=mascaras,
        )
    return None
