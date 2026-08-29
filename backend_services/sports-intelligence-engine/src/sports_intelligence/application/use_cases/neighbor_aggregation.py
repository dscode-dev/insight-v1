"""A agregação sobre o caminho projetado — orquestração, e não matemática nova.

O QUE ESTE MÓDULO ACRESCENTA É UMA AMARRA, e só ela: a política de ponderação
nasce da impressão da DEFINIÇÃO DE DISTÂNCIA que produziu os números.

    resultado exato  ->  distance_definition_fingerprint
                                  |
                                  v
                         política de ponderação
                                  |
                                  v
                              agregado

POR QUE ISSO IMPORTA. Os pesos são função da dissimilaridade, e a
dissimilaridade é definida por uma régua com impressão própria. Se a política
fosse construída com uma impressão qualquer, dois agregados medidos sob réguas
diferentes teriam a mesma identidade de política — e a impressão do agregado
deixaria de distinguir o que ela existe para distinguir.

A AGREGAÇÃO NÃO LÊ NADA (§27, §28). O `execute` abaixo tem duas fases nítidas:
a primeira recupera, e paga PostgreSQL; a segunda agrega, e não paga nada. O
tempo delas é medido separado justamente para que ninguém precise acreditar
nisso — `aggregate_ms` é o custo da transformação pura, e o teste de integração
conta as consultas dentro dessa segunda fase e exige zero.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.application.use_cases.projected_retrieval import (
    ProjectedTimings,
    RetrieveProjectedStateHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.projected_trajectory_retrieval import (
    RetrieveProjectedTrajectoryHistoricalNeighbors,
)
from sports_intelligence.domain.features.dataset.rows import HistoricalFeatureSnapshotKey
from sports_intelligence.domain.retrieval.aggregation.aggregate import NeighborAggregation
from sports_intelligence.domain.retrieval.aggregation.policy import (
    DistanceWeightingPolicy,
    state_weighting,
    trajectory_weighting,
)
from sports_intelligence.domain.retrieval.aggregation.summaries import (
    aggregate_state,
    aggregate_trajectory,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
)


@final
@dataclass(frozen=True, slots=True)
class AggregationOutcome:
    """O agregado, o resultado que o originou, e o que cada fase custou.

    O RESULTADO EXATO VIAJA JUNTO de propósito. O agregado guarda identidades e
    impressões, e não o payload dos vizinhos; quem precisar da evidência inteira
    a encontra aqui, sem uma segunda recuperação.
    """

    aggregation: NeighborAggregation
    result: Any
    policy: DistanceWeightingPolicy
    universe_rows: int
    retrieval_timings: ProjectedTimings
    #: O custo da AGREGAÇÃO PURA, já com o resultado exato em mãos (§62).
    aggregate_ms: float


def state_policy_for(result: Any, *, lam: float | None = None) -> DistanceWeightingPolicy:
    """A política de estado amarrada à régua que mediu este resultado."""
    impressao = result.distance_definition_fingerprint
    if lam is None:
        return state_weighting(distance_definition_fingerprint=impressao)
    return state_weighting(lam=lam, distance_definition_fingerprint=impressao)


def trajectory_policy_for(result: Any, *, lam: float | None = None) -> DistanceWeightingPolicy:
    """A de trajetória, pela mesma amarra e com o `lambda` dela."""
    impressao = result.distance_definition_fingerprint
    if lam is None:
        return trajectory_weighting(distance_definition_fingerprint=impressao)
    return trajectory_weighting(lam=lam, distance_definition_fingerprint=impressao)


@final
@dataclass(frozen=True, slots=True)
class AggregateProjectedStateNeighbors:
    """Recupera o top-K exato de ESTADO e o transforma em vizinhança ponderada."""

    projected: RetrieveProjectedStateHistoricalNeighbors

    async def execute(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        lam: float | None = None,
        candidate_policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
    ) -> AggregationOutcome:
        saida = await self.projected.execute(
            projection_version=projection_version,
            version_id=version_id,
            key=key,
            k=k,
            candidate_policy=candidate_policy,
        )
        # ---- daqui para baixo NENHUMA LEITURA acontece --------------------
        politica = state_policy_for(saida.result, lam=lam)
        marca = time.perf_counter()
        agregado = aggregate_state(
            saida.result, policy=politica, query_identity=key.text, requested_k=k
        )
        # As leituras derivadas entram na conta: são o que o consumidor pede.
        _ = agregado.effective_sample_size
        _ = agregado.top3_weight_mass
        _ = agregado.weighted_mean_dissimilarity
        custo = (time.perf_counter() - marca) * 1000

        return AggregationOutcome(
            aggregation=agregado,
            result=saida.result,
            policy=politica,
            universe_rows=saida.universe_rows,
            retrieval_timings=saida.timings,
            aggregate_ms=custo,
        )


@final
@dataclass(frozen=True, slots=True)
class AggregateProjectedTrajectoryNeighbors:
    """O mesmo para TRAJETÓRIA — e os dois caminhos nunca se encontram (§56)."""

    projected: RetrieveProjectedTrajectoryHistoricalNeighbors

    async def execute(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        lam: float | None = None,
        candidate_policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
    ) -> AggregationOutcome:
        saida = await self.projected.execute(
            projection_version=projection_version,
            version_id=version_id,
            key=key,
            k=k,
            candidate_policy=candidate_policy,
        )
        # ---- daqui para baixo NENHUMA LEITURA acontece --------------------
        politica = trajectory_policy_for(saida.result, lam=lam)
        marca = time.perf_counter()
        agregado = aggregate_trajectory(
            saida.result, policy=politica, query_identity=key.text, requested_k=k
        )
        _ = agregado.effective_sample_size
        _ = agregado.top3_weight_mass
        _ = agregado.weighted_mean_dissimilarity
        custo = (time.perf_counter() - marca) * 1000

        return AggregationOutcome(
            aggregation=agregado,
            result=saida.result,
            policy=politica,
            universe_rows=saida.universe_rows,
            retrieval_timings=saida.timings,
            aggregate_ms=custo,
        )
