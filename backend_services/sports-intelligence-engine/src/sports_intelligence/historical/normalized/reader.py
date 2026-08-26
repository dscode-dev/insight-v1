"""A leitura do dataset CRU — em lotes, projetada e podada.

O QUE ESTE MÓDULO EXISTE PARA NÃO FAZER: carregar noventa e uma mil linhas de
duzentas e trinta e três colunas na memória para depois transformá-las. Ele
devolve LOTES, e o tamanho do lote é decisão de quem chama.

TRÊS ECONOMIAS, E AS TRÊS SÃO DO FORMATO COLUNAR:

    poda de partição   o ajuste lê `split=REFERENCE` e não abre a avaliação
    projeção           o ajuste lê 29 eixos dos 105 e paga um quarto do custo
    lote               a memória não cresce com o tamanho do dataset

A PODA É POR PREFIXO DE CHAVE, e não por filtro depois de ler. Filtrar depois
funcionaria e leria o dobro — e, pior, faria a correção do ajuste depender de um
`if` em vez da estrutura do bucket (§29).

A ORDEM É CONTRATO. As partições saem em ordem canônica de
`(metade, competição, temporada, pedaço)`, e as linhas em ordem de arquivo
DENTRO de cada uma. As impressões deste PR são todas ordenadas e recusam a
inversão: um leitor que entregasse fora de ordem para a construção em vez de
produzir um dataset irreprodutível.

ELE NÃO REORDENA NADA. Se um arquivo foi gravado fora de ordem, isso é um
defeito do dataset cru, e a construção normalizada tem de PARAR ao vê-lo —
ordenar aqui esconderia o defeito e produziria um normalizado consistente sobre
um cru que não é.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Sequence
from typing import Any, Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.normalized.transform import RawFeatureRowView
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.historical.features.materializer import (
    AVAILABILITY_PREFIX,
    VALUE_PREFIX,
)
from sports_intelligence.ports.object_store import ObjectStorePort

#: As colunas de identidade que toda leitura precisa, independentemente da
#: projeção de features. Elas são sete de duzentas e trinta e três.
IDENTITY_PROJECTION: Final[tuple[str, ...]] = (
    "match_id",
    "grid_index",
    "grid_label",
    "period",
    "minute",
    "split",
    "competition",
    "season",
    "row_digest",
)

_SUFIXO: Final[str] = ".parquet"


@final
class ParquetRawFeatureDatasetReader:
    """Lê as linhas materializadas de uma versão crua."""

    def __init__(self, store: ObjectStorePort) -> None:
        self._store = store

    # ------------------------------------------------------------ partições --

    async def partitions(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
    ) -> Sequence[tuple[DatasetSplit, str, str]]:
        """As partições daquela versão, em ordem canônica e SEM repetição.

        UMA PARTIÇÃO PODE TER VÁRIOS PEDAÇOS (`part-00000`, `part-00001`), e o
        que volta daqui é a PARTIÇÃO — não o objeto. Quem quer os objetos usa
        `_objetos()`.
        """
        vistas: set[tuple[DatasetSplit, str, str]] = set()
        for chave in await self._objetos(dataset_name=dataset_name, version=version, split=split):
            vistas.add(_particao_da_chave(chave))
        return sorted(vistas, key=lambda p: (p[0].value, p[1], p[2]))

    async def _objetos(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
    ) -> list[str]:
        """As chaves de Parquet, ORDENADAS. O manifesto não entra."""
        prefixo = f"features/{dataset_name}/{version}/"
        if split is not None:
            prefixo += f"split={split.value}/"
        chaves = [
            chave async for chave in self._store.list_prefix(prefixo) if chave.endswith(_SUFIXO)
        ]
        return sorted(chaves)

    async def row_count(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
    ) -> int:
        """A contagem, SEM ler valor nenhum — do rodapé do Parquet.

        ELE EXISTE PARA O CONTRATO 1:1 (§94). Conferir a cardinalidade lendo as
        linhas faria a validação custar o mesmo que a construção.
        """
        import pyarrow.parquet as pq

        total = 0
        for chave in await self._objetos(dataset_name=dataset_name, version=version, split=split):
            bruto = await self._baixar(chave)
            total += int(pq.ParquetFile(io.BytesIO(bruto)).metadata.num_rows)
        return total

    # ---------------------------------------------------------------- fluxo --

    async def stream_rows(
        self,
        *,
        dataset_name: str,
        version: str,
        split: DatasetSplit | None = None,
        feature_keys: Sequence[str] | None = None,
        batch_rows: int = 2_000,
    ) -> AsyncIterator[Sequence[RawFeatureRowView]]:
        """As linhas em lotes, na ordem do arquivo, partição a partição."""
        if batch_rows < 1:
            raise ValidationError(f"lote de {batch_rows} linhas: ele precisa ser >= 1")
        import pyarrow.parquet as pq

        eixos = tuple(feature_keys) if feature_keys is not None else None
        for chave in await self._objetos(dataset_name=dataset_name, version=version, split=split):
            bruto = await self._baixar(chave)
            arquivo = pq.ParquetFile(io.BytesIO(bruto))
            colunas = _projecao(arquivo.schema_arrow.names, eixos)
            presentes = _eixos_presentes(arquivo.schema_arrow.names, eixos)
            for lote in arquivo.iter_batches(batch_size=batch_rows, columns=colunas):
                yield _para_views(lote, presentes)

    # ------------------------------------------------------------- interno --

    async def _baixar(self, chave: str) -> bytes:
        """O objeto inteiro em memória.

        UM PARQUET DE PARTIÇÃO É PEQUENO — a mediana medida no PR-05.5.1 foi de
        mil oitocentas e vinte linhas e algumas centenas de kB. O que precisa
        ser em fluxo é o DATASET, e é: um objeto de cada vez, um lote de cada
        vez. Fazer leitura aleatória sobre o bucket para economizar essas
        centenas de kB pagaria uma ida e volta por grupo de linhas.
        """
        buffer = bytearray()
        async for bloco in self._store.open_stream(chave):
            buffer.extend(bloco)
        return bytes(buffer)


def _particao_da_chave(chave: str) -> tuple[DatasetSplit, str, str]:
    """`split=X/competition=Y/season=Z` de volta, do caminho.

    ELE FAZ ANÁLISE SINTÁTICA DE CHAVE, e é o único lugar do PR que faz. O
    manifesto guarda a partição em colunas justamente para que a reconciliação
    NÃO dependa disto; aqui a fonte é o bucket, e o caminho é tudo que existe.
    """
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
    return (
        DatasetSplit(partes["split"]),
        partes["competition"],
        partes["season"],
    )


def _projecao(disponiveis: Sequence[str], feature_keys: Sequence[str] | None) -> list[str]:
    """As colunas a ler: identidade sempre, features conforme pedido."""
    if feature_keys is None:
        return [
            nome
            for nome in disponiveis
            if nome in IDENTITY_PROJECTION
            or nome.startswith(VALUE_PREFIX)
            or nome.startswith(AVAILABILITY_PREFIX)
        ]
    conjunto = set(disponiveis)
    colunas = [nome for nome in IDENTITY_PROJECTION if nome in conjunto]
    for chave in feature_keys:
        for nome in (f"{VALUE_PREFIX}{chave}", f"{AVAILABILITY_PREFIX}{chave}"):
            if nome in conjunto:
                colunas.append(nome)
    return colunas


def _eixos_presentes(
    disponiveis: Sequence[str], feature_keys: Sequence[str] | None
) -> tuple[str, ...]:
    """Os eixos que o arquivo de fato tem, na ordem pedida.

    UM EIXO PEDIDO E AUSENTE NÃO É ERRO AQUI. O dataset cru foi construído sob
    um catálogo, e o plano pode ter sido montado sob outro; quem confere essa
    compatibilidade é o caso de uso, com a impressão do espaço — e ele dá uma
    mensagem sobre versões de espaço em vez de uma sobre coluna faltando.
    """
    conjunto = set(disponiveis)
    if feature_keys is None:
        return tuple(
            nome[len(VALUE_PREFIX) :] for nome in disponiveis if nome.startswith(VALUE_PREFIX)
        )
    return tuple(chave for chave in feature_keys if f"{VALUE_PREFIX}{chave}" in conjunto)


def _para_views(lote: Any, eixos: Sequence[str]) -> list[RawFeatureRowView]:
    """Um `RecordBatch` do pyarrow em `RawFeatureRowView`.

    AS COLUNAS SÃO CONVERTIDAS UMA VEZ, e não célula a célula. `to_pylist()`
    por coluna faz uma travessia de Arrow para Python por COLUNA; fazê-lo por
    célula multiplicaria o custo pelo número de linhas do lote.
    """
    identidade = {nome: lote.column(nome).to_pylist() for nome in IDENTITY_PROJECTION}
    valores = {chave: lote.column(f"{VALUE_PREFIX}{chave}").to_pylist() for chave in eixos}
    mascaras = {chave: lote.column(f"{AVAILABILITY_PREFIX}{chave}").to_pylist() for chave in eixos}
    linhas: list[RawFeatureRowView] = []
    for i in range(lote.num_rows):
        linhas.append(
            RawFeatureRowView(
                key=HistoricalFeatureSnapshotKey(
                    match_key=str(identidade["match_id"][i]),
                    grid_index=int(identidade["grid_index"][i]),
                ),
                split=DatasetSplit(identidade["split"][i]),
                competition=str(identidade["competition"][i]),
                season=str(identidade["season"][i]),
                grid_index=int(identidade["grid_index"][i]),
                grid_label=str(identidade["grid_label"][i]),
                period=str(identidade["period"][i]),
                minute=int(identidade["minute"][i]),
                row_digest=str(identidade["row_digest"][i]),
                values={
                    chave: None if valores[chave][i] is None else float(valores[chave][i])
                    for chave in eixos
                },
                availabilities={chave: str(mascaras[chave][i]) for chave in eixos},
            )
        )
    return linhas
