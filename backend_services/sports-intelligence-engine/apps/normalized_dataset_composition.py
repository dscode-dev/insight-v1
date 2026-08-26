"""A composição do PR-05.5.2 — o grafo do ajuste e do dataset normalizado.

POR QUE UM ARQUIVO À PARTE, pela sexta vez: cada fase do motor monta o próprio
grafo, e a separação mantém visível o que cada uma EXIGE. Aqui a exigência nova
é dupla: um LEITOR do dataset cru e um MATERIALIZADOR do normalizado. Os dois
falam com o mesmo bucket e fazem coisas opostas.

O PLANO É ESCOLHIDO NA MONTAGEM, E NÃO POR CHAMADA. Ele depende da fronteira da
divisão — que é da versão crua —, então o contêiner recebe a fronteira e monta o
plano uma vez. Deixar cada caso de uso reconstruir o plano faria dois deles
divergirem no dia em que o catálogo mudasse no meio de uma execução.

O MATERIALIZADOR RECEBE O PLANO, e não o catálogo. O schema do Parquet
normalizado é três colunas por EIXO DO PLANO, e o plano é o que decide quais
eixos existem — passar o catálogo obrigaria o adaptador a reconstruir o plano
para saber a largura do arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.adapters.postgres.corpus import (
    PostgresHistoricalCorpusRepository,
)
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.feature_dataset import (
    PostgresHistoricalFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.normalized_dataset import (
    PostgresNormalizedDatasetBuildRepository,
    PostgresNormalizedFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.normalizer_artifacts import (
    PostgresNormalizerArtifactSetRepository,
)
from sports_intelligence.application.use_cases.normalized_dataset import (
    BUILD_BATCH_ROWS,
    DEFAULT_MAX_PENDING_ROWS,
    DEFAULT_PART_ROWS,
    FIT_BATCH_ROWS,
    BuildNormalizedFeatureDatasetVersion,
    CreateNormalizedFeatureDatasetVersion,
    FitNormalizerArtifactSet,
    PublishNormalizedFeatureDatasetVersion,
    ValidateNormalizedFeatureDatasetVersion,
    ValidateNormalizerArtifactSet,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ExtendedFeatureCatalog,
    extended_feature_catalog,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    plan_for,
)
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.historical.normalized.materializer import (
    ParquetNormalizedDatasetMaterializer,
)
from sports_intelligence.historical.normalized.reader import (
    ParquetRawFeatureDatasetReader,
)
from sports_intelligence.ports.object_store import ObjectStorePort


@final
@dataclass(frozen=True, slots=True)
class NormalizedDatasetContainer:
    """O grafo do PR-05.5.2, montado uma vez por processo."""

    plan: NormalizationPlan
    artifacts: PostgresNormalizerArtifactSetRepository
    datasets: PostgresNormalizedFeatureDatasetRepository
    builds: PostgresNormalizedDatasetBuildRepository
    reader: ParquetRawFeatureDatasetReader
    materializer: ParquetNormalizedDatasetMaterializer

    #: OS TAMANHOS VIAJAM NO CONTÊINER, e não em cada chamada. Eles são
    #: decisões de MEMÓRIA, e espalhá-los pelos chamadores é como dois caminhos
    #: — a CLI e o console — passam a construir sob tetos diferentes sem que
    #: nada denuncie até um deles estourar em produção.
    part_rows: int
    max_pending_rows: int
    fit_batch_rows: int
    build_batch_rows: int

    fit: FitNormalizerArtifactSet
    validate_artifacts: ValidateNormalizerArtifactSet
    create_version: CreateNormalizedFeatureDatasetVersion
    build_version: BuildNormalizedFeatureDatasetVersion
    validate_version: ValidateNormalizedFeatureDatasetVersion
    publish_version: PublishNormalizedFeatureDatasetVersion


def build_normalized_dataset_container(
    *,
    database: Database,
    clock: Any,
    audit: Any,
    store: ObjectStorePort,
    reference_end_exclusive: Instant,
    catalog: ExtendedFeatureCatalog | None = None,
    part_rows: int = DEFAULT_PART_ROWS,
    max_pending_rows: int = DEFAULT_MAX_PENDING_ROWS,
    fit_batch_rows: int = FIT_BATCH_ROWS,
    build_batch_rows: int = BUILD_BATCH_ROWS,
) -> NormalizedDatasetContainer:
    """Monta as seis etapas sobre um PostgreSQL e um object store.

    `reference_end_exclusive` É OBRIGATÓRIO porque ele entra na IDENTIDADE do
    plano (PR-05.1 §89): o plano de um ajuste até junho não é o plano de um
    ajuste até agosto. Um valor padrão aqui faria o contêiner montar um plano
    que não é o da versão que se pretende normalizar, e a divergência só
    apareceria como uma impressão que não fecha.
    """
    catalogo = catalog or extended_feature_catalog()
    plano = plan_for(
        reference_end_exclusive_normalizer=causal_dataset_normalizer(
            reference_end_exclusive=reference_end_exclusive
        ),
        catalog=catalogo,
    )

    artefatos = PostgresNormalizerArtifactSetRepository(database)
    normalizados = PostgresNormalizedFeatureDatasetRepository(database)
    execucoes = PostgresNormalizedDatasetBuildRepository(database)
    crus = PostgresHistoricalFeatureDatasetRepository(database)
    corpus = PostgresHistoricalCorpusRepository(database)
    leitor = ParquetRawFeatureDatasetReader(store)
    materializador = ParquetNormalizedDatasetMaterializer(store, plan=plano)

    return NormalizedDatasetContainer(
        plan=plano,
        artifacts=artefatos,
        datasets=normalizados,
        builds=execucoes,
        reader=leitor,
        materializer=materializador,
        part_rows=part_rows,
        max_pending_rows=max_pending_rows,
        fit_batch_rows=fit_batch_rows,
        build_batch_rows=build_batch_rows,
        fit=FitNormalizerArtifactSet(
            raw_datasets=crus,
            corpus=corpus,
            reader=leitor,
            artifacts=artefatos,
            clock=clock,
            audit=audit,
        ),
        validate_artifacts=ValidateNormalizerArtifactSet(
            artifacts=artefatos, raw_datasets=crus, clock=clock, audit=audit
        ),
        create_version=CreateNormalizedFeatureDatasetVersion(
            normalized=normalizados,
            raw_datasets=crus,
            artifacts=artefatos,
            clock=clock,
            audit=audit,
        ),
        build_version=BuildNormalizedFeatureDatasetVersion(
            normalized=normalizados,
            builds=execucoes,
            raw_datasets=crus,
            artifacts=artefatos,
            reader=leitor,
            materializer=materializador,
            clock=clock,
            audit=audit,
        ),
        validate_version=ValidateNormalizedFeatureDatasetVersion(
            normalized=normalizados,
            builds=execucoes,
            raw_datasets=crus,
            reader=leitor,
            materializer=materializador,
            clock=clock,
            audit=audit,
        ),
        publish_version=PublishNormalizedFeatureDatasetVersion(
            normalized=normalizados,
            builds=execucoes,
            materializer=materializador,
            clock=clock,
            audit=audit,
        ),
    )
