"""A composição da recuperação — os grafos do PR-06.1, do PR-06.2 e do PR-06.3.

POR QUE UM ARQUIVO À PARTE, pela sétima vez: cada fase monta o próprio grafo, e
a separação mantém visível o que cada uma EXIGE. Aqui a exigência é curta e
diz muito: dois repositórios de metadado e UM leitor de Parquet.

    normalized   a versão, o nome do dataset, a representação
    artifacts    os números do ajuste — medianas e IQRs, em `Decimal`
    source       as linhas, do object store

O PR-06.2 NÃO ACRESCENTA DEPENDÊNCIA NENHUMA a essa lista, e isso é o que se
esperava: a cobertura é uma decisão sobre as colunas que já estavam sendo
lidas. Um repositório novo aqui significaria que a política de ausência foi
completar um eixo em algum lugar — e é exatamente isso que o §16 proíbe.

NÃO HÁ REPOSITÓRIO DE FATO CANÔNICO NESTA LISTA, e a ausência é a garantia do
§6: a recuperação não tem por onde ler partida, evento, escalação, cotação ou
resultado, porque o contêiner não lhe dá nenhum.

O PLANO É MONTADO NA COMPOSIÇÃO, e o caso de uso o recebe por uma FÁBRICA. A
indireção existe para que ele não precise conhecer nem a fronteira da divisão
nem o catálogo de features — e o que a torna segura é a conferência: o caso de
uso recusa um plano cuja impressão não seja a que a versão normalizada declarou.

    A FRONTEIRA VEM DE QUEM MONTA O GRAFO, e não da versão normalizada. Ela é
    da versão CRUA de origem, que a declara na `spec`; a normalizada guarda a
    impressão do plano, e não os parâmetros dele. Buscá-la aqui custaria duas
    consultas a mais por processo para descobrir algo que o chamador já sabe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.adapters.postgres.feature_dataset import (
    PostgresHistoricalFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.normalized_dataset import (
    PostgresNormalizedFeatureDatasetRepository,
)
from sports_intelligence.adapters.postgres.normalizer_artifacts import (
    PostgresNormalizerArtifactSetRepository,
)
from sports_intelligence.adapters.postgres.retrieval_projection import (
    PostgresRetrievalProjectionReader,
    PostgresRetrievalProjectionRepository,
    PostgresRetrievalProjectionWriter,
)
from sports_intelligence.application.use_cases.availability_retrieval import (
    CompareExactRetrievalPolicies,
    RetrieveAvailabilityAwareHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.retrieval import (
    DEFAULT_CANDIDATE_BATCH_ROWS,
    DescribeCandidateUniverse,
    RetrieveExactHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.trajectory_retrieval import (
    CompareStateAndTrajectory,
    DescribeTrajectory,
    RetrieveExactHistoricalTrajectories,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
    plan_for,
)
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    TrajectoryCoveragePolicy,
)
from sports_intelligence.historical.retrieval.reader import (
    ParquetHistoricalCandidateSource,
)
from sports_intelligence.historical.retrieval.trajectory_reader import (
    ParquetHistoricalTrajectorySource,
)
from sports_intelligence.ports.object_store import ObjectStorePort


@final
@dataclass(frozen=True, slots=True)
class RetrievalContainer:
    """O grafo do PR-06.1, montado uma vez por processo."""

    plan: NormalizationPlan
    normalized: PostgresNormalizedFeatureDatasetRepository
    artifacts: PostgresNormalizerArtifactSetRepository
    source: ParquetHistoricalCandidateSource

    #: O LOTE VIAJA NO CONTÊINER, e não em cada chamada. Ele é decisão de
    #: MEMÓRIA, e espalhá-lo pelos chamadores é como dois caminhos — a CLI e o
    #: benchmark — passam a varrer sob tetos diferentes.
    batch_rows: int

    #: A POLÍTICA DE COBERTURA VIAJA NO CONTÊINER pelo mesmo motivo do lote:
    #: dois caminhos que a passassem por chamada acabariam medindo sob pisos
    #: diferentes, e os dois números pareceriam a mesma grandeza.
    coverage_policy: AvailabilityCoveragePolicy

    #: A política de trajetória viaja no contêiner pelo mesmo motivo.
    trajectory_coverage_policy: TrajectoryCoveragePolicy

    retrieve: RetrieveExactHistoricalNeighbors
    describe: DescribeCandidateUniverse
    #: O PR-06.2 — a mesma resolução e o mesmo universo, outra régua.
    retrieve_aware: RetrieveAvailabilityAwareHistoricalNeighbors
    compare: CompareExactRetrievalPolicies
    #: O PR-06.3 — o mesmo universo, outra PERGUNTA.
    raw_datasets: PostgresHistoricalFeatureDatasetRepository
    trajectory_source: ParquetHistoricalTrajectorySource
    retrieve_trajectory: RetrieveExactHistoricalTrajectories

    #: A PROJEÇÃO DO PR-06.4 VIAJA NO CONTÊINER como todo o resto.
    #:
    #: ELA NÃO É IMPORTADA PELA CLI. A guarda `apps não importam adapters
    #: diretamente` existe porque um app que instancia o adapter escolhe a
    #: infraestrutura por conta própria — e no dia em que houver um segundo
    #: armazenamento, é ele que fica para trás. A composição é o único lugar
    #: que decide isso.
    projection_repository: PostgresRetrievalProjectionRepository
    projection_writer: PostgresRetrievalProjectionWriter
    projection_reader: PostgresRetrievalProjectionReader
    describe_trajectory: DescribeTrajectory
    compare_state_trajectory: CompareStateAndTrajectory


def build_retrieval_container(
    *,
    database: Database,
    store: ObjectStorePort,
    reference_end_exclusive: Any,
    batch_rows: int = DEFAULT_CANDIDATE_BATCH_ROWS,
    coverage_policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY,
    trajectory_coverage_policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE,
) -> RetrievalContainer:
    """Monta a recuperação sobre um PostgreSQL e um object store.

    `reference_end_exclusive` É OBRIGATÓRIO pelo mesmo motivo do PR-05.5.2: o
    corte entra na IDENTIDADE do plano, e um valor padrão faria o contêiner
    montar um plano que não é o da versão que se pretende consultar — a
    divergência apareceria como uma impressão que não fecha, e não como uma
    configuração errada.
    """
    plano = plan_for(
        reference_end_exclusive_normalizer=causal_dataset_normalizer(
            reference_end_exclusive=reference_end_exclusive
        )
    )
    normalizados = PostgresNormalizedFeatureDatasetRepository(database)
    artefatos = PostgresNormalizerArtifactSetRepository(database)
    leitor = ParquetHistoricalCandidateSource(store)

    recuperar = RetrieveExactHistoricalNeighbors(
        normalized=normalizados,
        artifacts=artefatos,
        source=leitor,
        # A FÁBRICA IGNORA A VERSÃO e devolve o plano montado aqui. Ela existe
        # como função para que o caso de uso não precise conhecer nem a
        # fronteira nem o catálogo — e a conferência de impressão dele é o que
        # transforma essa indireção em garantia.
        plan_factory=lambda _versao: plano,
        batch_rows=batch_rows,
    )
    # O PR-06.2 COMPÕE O PR-06.1, e não o substitui: `resolve_base` e
    # `candidates` são os mesmos, então o universo dos dois é o mesmo por
    # construção — e a comparação entre eles mede a política de ausência.
    ciente = RetrieveAvailabilityAwareHistoricalNeighbors(
        exact=recuperar, coverage_policy=coverage_policy
    )
    # O PR-06.3 ACRESCENTA DUAS DEPENDÊNCIAS, e as duas são de METADADO ou de
    # object store — nenhuma é fato canônico. `raw_datasets` existe para ler a
    # GRADE da versão crua de origem: a compatibilidade de lookback é um fato
    # do dataset, e recebê-la por parâmetro faria a conferência validar o que o
    # chamador disse em vez do que o dataset é.
    datasets_crus = PostgresHistoricalFeatureDatasetRepository(database)
    leitor_de_trajetoria = ParquetHistoricalTrajectorySource(store)
    trajetorias = RetrieveExactHistoricalTrajectories(
        exact=recuperar,
        raw_datasets=datasets_crus,
        trajectory_source=leitor_de_trajetoria,
        coverage_policy=trajectory_coverage_policy,
    )
    return RetrievalContainer(
        plan=plano,
        normalized=normalizados,
        artifacts=artefatos,
        source=leitor,
        batch_rows=batch_rows,
        coverage_policy=coverage_policy,
        retrieve=recuperar,
        describe=DescribeCandidateUniverse(retriever=recuperar, source=leitor),
        trajectory_coverage_policy=trajectory_coverage_policy,
        retrieve_aware=ciente,
        compare=CompareExactRetrievalPolicies(exact=recuperar, aware=ciente),
        raw_datasets=datasets_crus,
        trajectory_source=leitor_de_trajetoria,
        retrieve_trajectory=trajetorias,
        projection_repository=PostgresRetrievalProjectionRepository(database),
        projection_writer=PostgresRetrievalProjectionWriter(database),
        projection_reader=PostgresRetrievalProjectionReader(database),
        describe_trajectory=DescribeTrajectory(retriever=trajetorias),
        compare_state_trajectory=CompareStateAndTrajectory(state=ciente, trajectory=trajetorias),
    )
