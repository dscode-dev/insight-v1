"""A composição do PR-04.3 — o grafo da publicação do corpus histórico.

POR QUE UM ARQUIVO À PARTE, pela quarta vez: `composition.py` monta o intake,
`resolution_composition.py` o PR-03, `build_composition.py` o PR-04.2, e este
monta a publicação. A separação mantém cada grafo legível e, sobretudo, mantém
o que cada fase EXIGE visível — quem lê este arquivo vê que a publicação
precisa de um leitor de composição e de um materializador, e de mais nada.

O MATERIALIZADOR É OPCIONAL AQUI TAMBÉM (ADR-0027). `build_corpus_container`
aceita `store=None`, e o contêiner resultante publica sem Parquet. É o que
permite a um ambiente sem object store publicar um corpus completo — a verdade
está no PostgreSQL, e o arquivo é representação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.adapters.postgres.corpus import (
    PostgresCanonicalManifestRepository,
    PostgresCorpusCompositionReader,
    PostgresCorpusEventReader,
    PostgresCorpusMembershipRepository,
    PostgresHistoricalCorpusRepository,
)
from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.quality import (
    PostgresQualityAssessmentRepository,
)
from sports_intelligence.application.use_cases.corpus import (
    DEFAULT_COMPOSITION_BATCH,
    BuildCorpusVersion,
    CreateHistoricalDataset,
    PublishCorpusVersion,
)
from sports_intelligence.domain.quality.policy import (
    DEFAULT_QUALITY_POLICY,
    HistoricalQualityPolicy,
)
from sports_intelligence.historical.corpus.materializer import ParquetCorpusMaterializer
from sports_intelligence.ports.object_store import ObjectStorePort


@final
@dataclass(frozen=True, slots=True)
class CorpusContainer:
    """O grafo do PR-04.3, montado uma vez por processo."""

    datasets: PostgresHistoricalCorpusRepository
    membership: PostgresCorpusMembershipRepository
    manifests: PostgresCanonicalManifestRepository
    composition: PostgresCorpusCompositionReader
    #: O leitor dos eventos que uma versão publica (PR-04.4.2). Ele está sempre
    #: montado; o que decide se eventos entram é a VERSÃO, que declara — ou não
    #: — execuções de canonicalização de evento.
    events: PostgresCorpusEventReader

    create_dataset: CreateHistoricalDataset
    build_version: BuildCorpusVersion
    publish_version: PublishCorpusVersion

    #: `None` quando o processo publica sem Parquet. Nomeado para que a
    #: ausência apareça em quem lê o contêiner, e não só no comportamento.
    materializer: ParquetCorpusMaterializer | None = None


def build_corpus_container(
    *,
    database: Database,
    clock: Any,
    audit: Any,
    store: ObjectStorePort | None = None,
    quality_policy: HistoricalQualityPolicy = DEFAULT_QUALITY_POLICY,
    batch_size: int = DEFAULT_COMPOSITION_BATCH,
) -> CorpusContainer:
    datasets = PostgresHistoricalCorpusRepository(database)
    membership = PostgresCorpusMembershipRepository(database)
    manifests = PostgresCanonicalManifestRepository(database)
    composicao = PostgresCorpusCompositionReader(database)
    eventos = PostgresCorpusEventReader(database)
    assessments = PostgresQualityAssessmentRepository(database)
    materializador = None if store is None else ParquetCorpusMaterializer(store)

    return CorpusContainer(
        datasets=datasets,
        membership=membership,
        manifests=manifests,
        composition=composicao,
        events=eventos,
        create_dataset=CreateHistoricalDataset(datasets=datasets, clock=clock, audit=audit),
        build_version=BuildCorpusVersion(
            datasets=datasets,
            membership=membership,
            composition=composicao,
            events=eventos,
            assessments=assessments,
            manifests=manifests,
            clock=clock,
            audit=audit,
            materializer=materializador,
            quality_policy=quality_policy,
            batch_size=batch_size,
        ),
        publish_version=PublishCorpusVersion(
            datasets=datasets,
            membership=membership,
            manifests=manifests,
            clock=clock,
            audit=audit,
            materializer=materializador,
        ),
        materializer=materializador,
    )
