"""A composição do PR-05.5.1 — o grafo da materialização do dataset de features.

POR QUE UM ARQUIVO À PARTE, pela quinta vez: `composition.py` monta o intake,
`resolution_composition.py` o PR-03, `build_composition.py` o PR-04.2,
`corpus_composition.py` a publicação do corpus, e este monta a materialização
das features. A separação mantém cada grafo legível e, sobretudo, mantém o que
cada fase EXIGE visível.

O MATERIALIZADOR NÃO É OPCIONAL AQUI, e essa é a diferença que se lê no tipo
(ADR-0037). No corpus, `store=None` produz um contêiner que publica sem
Parquet — a verdade está no PostgreSQL, e o arquivo é representação. Aqui as
LINHAS moram no arquivo: um contêiner sem object store não teria onde escrever
o dataset, e a assinatura recusa montá-lo.

AS DEFINIÇÕES ENTRAM NO MATERIALIZADOR, e não no caso de uso. O schema do
Parquet é derivado do catálogo, e é o adaptador que o conhece — quem monta o
grafo escolhe o catálogo uma vez, e o schema deixa de poder divergir entre duas
partições da mesma versão.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.adapters.postgres.corpus import (
    PostgresHistoricalCorpusRepository,
)
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.feature_context import (
    PostgresHistoricalContextSource,
)
from sports_intelligence.adapters.postgres.feature_dataset import (
    PostgresFeatureDatasetBuildRepository,
    PostgresFeatureDatasetManifestRepository,
    PostgresHistoricalFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.feature_state import (
    PostgresHistoricalMatchStateSource,
)
from sports_intelligence.application.use_cases.feature_dataset import (
    DEFAULT_PART_ROWS,
    DEFAULT_REBUILD_SAMPLE,
    BuildHistoricalFeatureDatasetVersion,
    CreateHistoricalFeatureDatasetVersion,
    PublishHistoricalFeatureDatasetVersion,
    ValidateHistoricalFeatureDatasetVersion,
)
from sports_intelligence.application.use_cases.feature_state import DEFAULT_STATE_BATCH
from sports_intelligence.domain.features.availability import TemporalAvailabilityPolicy
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    ExtendedFeatureCatalog,
    extended_feature_catalog,
)
from sports_intelligence.historical.features.materializer import (
    ParquetFeatureDatasetMaterializer,
)
from sports_intelligence.ports.object_store import ObjectStorePort


@final
@dataclass(frozen=True, slots=True)
class FeatureDatasetContainer:
    """O grafo do PR-05.5.1, montado uma vez por processo."""

    datasets: PostgresHistoricalFeatureDatasetRepository
    builds: PostgresFeatureDatasetBuildRepository
    manifests: PostgresFeatureDatasetManifestRepository
    materializer: ParquetFeatureDatasetMaterializer

    create_version: CreateHistoricalFeatureDatasetVersion
    build_version: BuildHistoricalFeatureDatasetVersion
    validate_version: ValidateHistoricalFeatureDatasetVersion
    publish_version: PublishHistoricalFeatureDatasetVersion


def build_feature_dataset_container(
    *,
    database: Database,
    clock: Any,
    audit: Any,
    store: ObjectStorePort,
    catalog: ExtendedFeatureCatalog | None = None,
    policy: TemporalAvailabilityPolicy | None = None,
    batch_size: int = DEFAULT_STATE_BATCH,
    part_rows: int = DEFAULT_PART_ROWS,
    rebuild_sample: int = DEFAULT_REBUILD_SAMPLE,
) -> FeatureDatasetContainer:
    """Monta as quatro fases sobre um PostgreSQL e um object store.

    `store` É OBRIGATÓRIO, e o `|None` do corpus não existe aqui de propósito
    (ADR-0037). Uma versão sem materialização não é uma versão com menos
    comodidade: é uma versão sem conteúdo.
    """
    catalogo = catalog or extended_feature_catalog()
    temporal = policy or TemporalAvailabilityPolicy.default()

    versoes = PostgresHistoricalFeatureDatasetRepository(database)
    execucoes = PostgresFeatureDatasetBuildRepository(database)
    manifestos = PostgresFeatureDatasetManifestRepository(database)
    corpus = PostgresHistoricalCorpusRepository(database)
    estado = PostgresHistoricalMatchStateSource(database)
    contexto = PostgresHistoricalContextSource(database)
    materializador = ParquetFeatureDatasetMaterializer(store, definitions=catalogo.definitions)

    return FeatureDatasetContainer(
        datasets=versoes,
        builds=execucoes,
        manifests=manifestos,
        materializer=materializador,
        create_version=CreateHistoricalFeatureDatasetVersion(
            datasets=versoes, corpus=corpus, clock=clock, audit=audit
        ),
        build_version=BuildHistoricalFeatureDatasetVersion(
            datasets=versoes,
            builds=execucoes,
            manifests=manifestos,
            state_source=estado,
            context_source=contexto,
            materializer=materializador,
            clock=clock,
            audit=audit,
            policy=temporal,
            catalog=catalogo,
            batch_size=batch_size,
            part_rows=part_rows,
        ),
        validate_version=ValidateHistoricalFeatureDatasetVersion(
            datasets=versoes,
            builds=execucoes,
            manifests=manifestos,
            materializer=materializador,
            state_source=estado,
            context_source=contexto,
            clock=clock,
            audit=audit,
            policy=temporal,
            catalog=catalogo,
            rebuild_sample=rebuild_sample,
        ),
        publish_version=PublishHistoricalFeatureDatasetVersion(
            datasets=versoes,
            manifests=manifestos,
            materializer=materializador,
            clock=clock,
            audit=audit,
        ),
    )
