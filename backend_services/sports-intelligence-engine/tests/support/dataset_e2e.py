"""A montagem do dataset de features contra PostgreSQL e object store reais.

POR QUE ELA MORA EM `tests/support` E NÃO NUM ARQUIVO DE TESTE. Dois E2E a
usam — o do caminho feliz e o da cadeia de integridade —, e importar fixture de
um módulo de teste para outro faz o `pytest` registrar a mesma função duas
vezes. Os FIXTURES ficam no `conftest` da integração; o que está aqui é a
montagem e os auxiliares, que são objetos comuns.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import timedelta
from typing import Any

from sports_intelligence.adapters.postgres.audit import PostgresAuditLog
from sports_intelligence.adapters.postgres.corpus import PostgresHistoricalCorpusRepository
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
    BuildHistoricalFeatureDatasetVersion,
    CreateHistoricalFeatureDatasetVersion,
    PublishHistoricalFeatureDatasetVersion,
    ValidateHistoricalFeatureDatasetVersion,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.dataset.grid import (
    DEFAULT_SNAPSHOT_GRID,
)
from sports_intelligence.domain.features.dataset.split import FeatureDatasetSplitPolicy
from sports_intelligence.domain.features.dataset.versions import (
    DEFAULT_FEATURE_DATASET_NAME,
    FEATURE_DATASET_PUBLISHER,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.temporal import instant
from sports_intelligence.domain.shared.versioning import DatasetVersion
from sports_intelligence.historical.features.materializer import (
    ParquetFeatureDatasetMaterializer,
)
from sports_intelligence.ports.clock import SystemClock

ATOR = Actor.service(FEATURE_DATASET_PUBLISHER)
NOME = DEFAULT_FEATURE_DATASET_NAME

#: 233 = 23 colunas de identidade e linhagem + 105 valores + 105
#: disponibilidades. O número é conferido à mão porque é o contrato do arquivo.
COLUNAS_ESPERADAS = 233


def origem_publicada(publicado: dict[str, Any]) -> CorpusSource:
    manifesto = publicado["manifest"]
    return CorpusSource.of(
        publicado["version"],
        published_families=frozenset(
            CoverageFamily(f.family)
            for f in manifesto.coverage
            if f.state != CoverageState.NOT_DECLARED.value
        ),
    )


class Montagem:
    """Os quatro casos de uso sobre PostgreSQL e object store de verdade."""

    def __init__(self, database: Database, object_store: Any) -> None:
        self.database = database
        self.repo = PostgresHistoricalFeatureDatasetRepository(database)
        self.builds = PostgresFeatureDatasetBuildRepository(database)
        self.manifests = PostgresFeatureDatasetManifestRepository(database)
        self.corpus = PostgresHistoricalCorpusRepository(database)
        self.estado = PostgresHistoricalMatchStateSource(database)
        self.contexto = PostgresHistoricalContextSource(database)
        self.materializer = ParquetFeatureDatasetMaterializer(
            object_store, definitions=extended_feature_catalog().definitions
        )
        self.clock = SystemClock()
        self.audit = PostgresAuditLog(database)

    @property
    def criar(self) -> CreateHistoricalFeatureDatasetVersion:
        return CreateHistoricalFeatureDatasetVersion(
            datasets=self.repo, corpus=self.corpus, clock=self.clock, audit=self.audit
        )

    @property
    def construir(self) -> BuildHistoricalFeatureDatasetVersion:
        return BuildHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            state_source=self.estado,
            context_source=self.contexto,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )

    @property
    def validar(self) -> ValidateHistoricalFeatureDatasetVersion:
        return ValidateHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            builds=self.builds,
            manifests=self.manifests,
            materializer=self.materializer,
            state_source=self.estado,
            context_source=self.contexto,
            clock=self.clock,
            audit=self.audit,
            # O DATASET É PEQUENO: reconstruir TODAS as partidas é o certo
            # aqui, e é o que o §120 pede do E2E.
            rebuild_sample=50,
        )

    @property
    def publicar(self) -> PublishHistoricalFeatureDatasetVersion:
        return PublishHistoricalFeatureDatasetVersion(
            datasets=self.repo,
            manifests=self.manifests,
            materializer=self.materializer,
            clock=self.clock,
            audit=self.audit,
        )


async def divisao_do_corpus(
    database: Database, publicado: dict[str, Any]
) -> FeatureDatasetSplitPolicy:
    """Uma fronteira DEPOIS de tudo que a versão publica.

    ELA PÕE TODO O CORPUS NA REFERÊNCIA, e é deliberado: o cenário do E2E tem
    poucas partidas, e uma fronteira no meio produziria uma metade de avaliação
    com uma delas — o que testaria a divisão e nada mais. A atomicidade e a
    monotonia já são provadas pelos portões de propriedade; o que este E2E
    prova é a MATERIALIZAÇÃO.

    A FRONTEIRA SAI DO BANCO, e não de uma data escrita à mão: uma constante
    passaria a estar no passado no dia em que o cenário mudasse de ano, e o
    dataset viraria avaliação inteira sem que ninguém entendesse por quê.
    """
    async with database.acquire() as conexao:
        ultimo = await conexao.fetchval(
            """
            SELECT max(m.scheduled_kickoff)
            FROM historical_canonical_members hcm
            JOIN matches m ON m.id = hcm.match_id
            WHERE hcm.version_id = $1
            """,
            _uuid.UUID(publicado["version"].id),
        )
    assert ultimo is not None, "a versão publicada precisa ter partidas"
    return FeatureDatasetSplitPolicy(reference_end_exclusive=instant(ultimo + timedelta(days=1)))


async def construir_versao(
    montagem: Montagem,
    publicado: dict[str, Any],
    *,
    version: DatasetVersion | None = None,
    dataset_name: str = NOME,
) -> Any:
    origem = origem_publicada(publicado)
    versao = await montagem.criar.execute(
        dataset_name=dataset_name,
        version=version or DatasetVersion(major=1, minor=0),
        source_version_id=origem.version_id,
        split=await divisao_do_corpus(montagem.database, publicado),
        grid=DEFAULT_SNAPSHOT_GRID,
        actor=ATOR,
        # A CONFERÊNCIA PRÉVIA É DISPENSADA AQUI, e o teste
        # `test_a_conferencia_previa_recusa_este_corpus` prova que ela existe e
        # funciona. O cenário não publica `LINEUP`, e é com ele assim que este
        # E2E prova o que veio provar: as dimensões de escalação chegam ao
        # Parquet como `NULL` com `NOT_DECLARED` ao lado, e nunca como zero.
        published_families=None,
    )
    saida = await montagem.construir.execute(
        version_id=versao.id,
        source=origem,
        dataset_name=dataset_name,
        actor=ATOR,
    )
    return saida
