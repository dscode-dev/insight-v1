"""A montagem da recuperação contra PostgreSQL e object store reais.

ELA LEVA O DATASET NORMALIZADO ATÉ `READY` e monta o grafo do PR-06.1 sobre ele.
O caminho inteiro — corpus, dataset cru, ajuste, normalização — já está montado
pelos fixtures do PR-05; o que este módulo acrescenta são os dois últimos
passos: publicar, e consultar.
"""

from __future__ import annotations

from typing import Any

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.corpus.versions import DatasetVersionStatus
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
)
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.temporal import Instant
from tests.support.normalized_e2e import ATOR, NOME, MontagemNormalizada

#: Quantos vizinhos os cenários pedem por padrão. Cinco cabem numa asserção
#: legível e passam do topo do heap mais de uma vez.
K_PADRAO: int = 5


async def publicar_versao_normalizada(normalizado: dict[str, Any]) -> dict[str, Any]:
    """Ajuste conferido, versão criada, construída, validada e PUBLICADA."""
    from sports_intelligence.domain.shared.versioning import DatasetVersion

    montagem: MontagemNormalizada = normalizado["montagem_n"]
    crua = normalizado["versao_crua"]
    conjunto = normalizado["ajuste"].artifact_set

    relatorio = await montagem.conferir_ajuste.execute(
        artifact_set_id=conjunto.id,
        actor=ATOR,
        reason="E2E do PR-06.1: o ajuste conferido autoriza normalizar",
    )
    assert relatorio.passed, relatorio.divergences

    versao = await montagem.criar.execute(
        version=DatasetVersion(major=1, minor=0),
        source_version_id=crua.id,
        artifact_set_id=conjunto.id,
        dataset_name=NOME,
        actor=ATOR,
    )
    await montagem.construir.execute(
        version_id=versao.id,
        dataset_name=NOME,
        raw_dataset_name=DEFAULT_FEATURE_DATASET_NAME,
        actor=ATOR,
    )
    conferencia = await montagem.validar.execute(
        version_id=versao.id,
        raw_dataset_name=DEFAULT_FEATURE_DATASET_NAME,
        actor=ATOR,
    )
    assert conferencia.passed, conferencia.failures
    publicada = await montagem.publicar.execute(
        version_id=versao.id,
        dataset_name=NOME,
        actor=ATOR,
        reason="E2E do PR-06.1: a recuperação exige a versão publicada",
    )
    assert publicada.status is DatasetVersionStatus.READY
    return {**normalizado, "versao_n": publicada}


def montar_recuperacao(
    database: Database,
    object_store: Any,
    *,
    reference_end_exclusive: Instant,
    batch_rows: int = 2_000,
) -> Any:
    """O contêiner do PR-06.1 sobre a infraestrutura de verdade."""
    from apps.retrieval_composition import build_retrieval_container

    return build_retrieval_container(
        database=database,
        store=object_store,
        reference_end_exclusive=reference_end_exclusive,
        batch_rows=batch_rows,
    )


async def queries_disponiveis(
    fonte: Any, *, dataset_name: str, version: str, limite: int = 50
) -> list[tuple[HistoricalFeatureSnapshotKey, GridTimePoint]]:
    """As chaves de AVALIAÇÃO do dataset, com o instante de cada uma.

    ELAS VÊM DO PARQUET, e não de uma constante. Uma chave escrita à mão
    passaria a apontar para nada no dia em que o cenário mudasse, e o teste
    falharia dizendo «linha não existe» — que é a mensagem menos útil possível.

    ELA LÊ QUATRO COLUNAS de trezentas e trinta: identidade e instante. Escolher
    uma query não pode custar a leitura dos valores.
    """
    import io

    import pyarrow.parquet as pq

    from sports_intelligence.domain.features.dataset.split import DatasetSplit

    encontradas: list[tuple[HistoricalFeatureSnapshotKey, GridTimePoint]] = []
    for chave in await fonte._objetos(
        dataset_name=dataset_name, version=version, split=DatasetSplit.EVALUATION
    ):
        bruto = await fonte._baixar(chave)
        tabela = pq.read_table(
            io.BytesIO(bruto), columns=["match_id", "grid_index", "period", "minute"]
        )
        for partida, indice, fase, minuto in zip(
            tabela.column("match_id").to_pylist(),
            tabela.column("grid_index").to_pylist(),
            tabela.column("period").to_pylist(),
            tabela.column("minute").to_pylist(),
            strict=True,
        ):
            encontradas.append(
                (
                    HistoricalFeatureSnapshotKey(match_key=str(partida), grid_index=int(indice)),
                    GridTimePoint.from_columns(period=str(fase), minute=int(minuto)),
                )
            )
            if len(encontradas) >= limite:
                return encontradas
    return encontradas


# ================================ o corpus de várias partidas ==


async def montar_corpus_de_recuperacao(database: Database, object_store: Any) -> dict[str, Any]:
    """O corpus READY do cenário de doze partidas, pelo caminho real.

    ELE REUSA `montar_corpus_publicado` com os parâmetros do PR-06.1. Nada é
    montado em memória: a diferença para o cenário do PR-05 é o conteúdo das
    fontes, e não o caminho que elas percorrem.
    """
    from tests.integration.test_match_state_e2e import (
        _CABECALHO,
        _REGIME,
        EVENTOS,
        montar_corpus_publicado,
    )
    from tests.support import retrieval_scenario as roteiro

    corpus = roteiro.cenario(_REGIME)
    return await montar_corpus_publicado(
        database,
        object_store,
        cenario=corpus,
        fonte_publica=roteiro.fonte_publica(corpus),
        fonte_de_eventos=roteiro.fonte_de_eventos(corpus, _CABECALHO),
        traducoes=roteiro.semear_traducoes(EVENTOS),
        tabela_de_tipos=roteiro.tabela_de_tipos(EVENTOS),
    )
