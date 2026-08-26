"""A montagem do ajuste e do dataset normalizado contra infraestrutura real.

POR QUE ELA MORA EM `tests/support`, pela mesma razão do `dataset_e2e`: mais de
um E2E a usa, e importar fixture de um módulo de teste para outro faz o
`pytest` registrar a mesma função duas vezes.

O QUE ELA ACRESCENTA AO `dataset_e2e`. Aquele para em `VALIDATING`; o ajuste
exige uma versão crua PUBLICADA — normalizar sobre um dataset não publicado
produziria uma escala sobre linhas que ainda podem mudar. Então aqui a versão
crua é levada até `READY` antes de qualquer coisa.
"""

from __future__ import annotations

from typing import Any

from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
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
    BuildNormalizedFeatureDatasetVersion,
    CreateNormalizedFeatureDatasetVersion,
    FitNormalizerArtifactSet,
    PublishNormalizedFeatureDatasetVersion,
    ValidateNormalizedFeatureDatasetVersion,
    ValidateNormalizerArtifactSet,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    plan_for,
)
from sports_intelligence.domain.features.normalized.versions import (
    DEFAULT_NORMALIZED_DATASET_NAME,
    NORMALIZED_DATASET_PUBLISHER,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.historical.normalized.materializer import (
    ParquetNormalizedDatasetMaterializer,
)
from sports_intelligence.historical.normalized.reader import (
    ParquetRawFeatureDatasetReader,
)
from sports_intelligence.ports.clock import SystemClock
from tests.support.dataset_e2e import ATOR as ATOR_CRU
from tests.support.dataset_e2e import NOME as NOME_CRU

ATOR = Actor.service(NORMALIZED_DATASET_PUBLISHER)
NOME = DEFAULT_NORMALIZED_DATASET_NAME

#: 15 colunas de identidade e linhagem mais tres por eixo (105).
COLUNAS_ESPERADAS = 15 + 3 * 105


class MontagemNormalizada:
    """As seis etapas sobre PostgreSQL e object store de verdade."""

    def __init__(
        self,
        database: Database,
        object_store: Any,
        *,
        reference_end_exclusive: Instant,
    ) -> None:
        self.database = database
        self.plan: NormalizationPlan = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=reference_end_exclusive
            )
        )
        self.artifacts = PostgresNormalizerArtifactSetRepository(database)
        self.datasets = PostgresNormalizedFeatureDatasetRepository(database)
        self.builds = PostgresNormalizedDatasetBuildRepository(database)
        self.raw = PostgresHistoricalFeatureDatasetRepository(database)
        self.corpus = PostgresHistoricalCorpusRepository(database)
        self.reader = ParquetRawFeatureDatasetReader(object_store)
        self.materializer = ParquetNormalizedDatasetMaterializer(object_store, plan=self.plan)
        self.clock = SystemClock()
        self.audit = PostgresAuditLog(database)

    @property
    def ajustar(self) -> FitNormalizerArtifactSet:
        return FitNormalizerArtifactSet(
            raw_datasets=self.raw,
            corpus=self.corpus,
            reader=self.reader,
            artifacts=self.artifacts,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def conferir_ajuste(self) -> ValidateNormalizerArtifactSet:
        return ValidateNormalizerArtifactSet(
            artifacts=self.artifacts,
            raw_datasets=self.raw,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def criar(self) -> CreateNormalizedFeatureDatasetVersion:
        return CreateNormalizedFeatureDatasetVersion(
            normalized=self.datasets,
            raw_datasets=self.raw,
            artifacts=self.artifacts,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def construir(self) -> BuildNormalizedFeatureDatasetVersion:
        return BuildNormalizedFeatureDatasetVersion(
            normalized=self.datasets,
            builds=self.builds,
            raw_datasets=self.raw,
            artifacts=self.artifacts,
            reader=self.reader,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def validar(self) -> ValidateNormalizedFeatureDatasetVersion:
        return ValidateNormalizedFeatureDatasetVersion(
            normalized=self.datasets,
            builds=self.builds,
            raw_datasets=self.raw,
            reader=self.reader,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def publicar(self) -> PublishNormalizedFeatureDatasetVersion:
        return PublishNormalizedFeatureDatasetVersion(
            normalized=self.datasets,
            builds=self.builds,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )


async def publicar_versao_crua(construido: dict[str, Any]) -> Any:
    """Leva a versão crua de `VALIDATING` a `READY`.

    O AJUSTE EXIGE UMA VERSÃO PUBLICADA (§26). Normalizar sobre um dataset que
    ainda pode mudar produziria uma escala sobre linhas que não são as finais —
    e a impressão do ajuste apontaria para um conteúdo que deixou de existir.
    """
    montagem = construido["montagem"]
    version_id = construido["saida"].version.id
    origem = construido["publicado"]
    from tests.support.dataset_e2e import origem_publicada

    relatorio = await montagem.validar.execute(
        version_id=version_id, source=origem_publicada(origem), actor=ATOR_CRU
    )
    assert relatorio.passed, relatorio.failures()
    return await montagem.publicar.execute(
        version_id=version_id,
        dataset_name=NOME_CRU,
        actor=ATOR_CRU,
        reason="E2E do PR-05.5.2: o ajuste exige uma versão crua publicada",
    )
