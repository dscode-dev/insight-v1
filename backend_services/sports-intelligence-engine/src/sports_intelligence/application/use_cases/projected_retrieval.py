"""Os recuperadores PROJETADOS — orquestradores, e não uma nova matemática.

O QUE ELES FAZEM, E SÓ ISSO:

    resolve a query        (o mesmo caminho do PR-06.2 / PR-06.3)
    lê o universo EXATO    (uma consulta ao PostgreSQL)
    reconstrói candidatos  (tipos do domínio, sem perder um bit)
    ENTREGA AO RETRIEVER EXATO QUE JÁ EXISTE

A ÚLTIMA LINHA É O PR INTEIRO. Não há aqui fórmula de distância, piso de
cobertura, regra de desempate ou montagem de evidência: tudo isso é
`AvailabilityAwareHistoricalRetriever` e `ExactTrajectoryRetriever`, os mesmos
objetos que a varredura sobre Parquet usa. O caminho projetado muda DE ONDE os
candidatos vêm, e nunca COMO eles são medidos.

    Parquet    MinIO -> pyarrow -> CandidateRow -> retriever exato -> top-K
    projetado  PostgreSQL -> bytea -> CandidateRow -> retriever exato -> top-K
                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                      e daqui em diante é byte a byte igual

POR QUE ISSO É MAIS FORTE QUE UM TESTE. Se o cálculo fosse reescrito aqui,
«mesma resposta» seria uma coincidência a ser verificada; sendo o MESMO objeto,
é uma propriedade estrutural. No dia em que o PR-06.2 corrigir a penalidade, os
dois caminhos mudam juntos porque são o mesmo código.

E NÃO HÁ LISTA CURTA. O universo é uma competição num instante exato — pequeno
por construção —, e devolvê-lo inteiro custa menos que aproximá-lo. A medição
que sustenta isso está em `ANN_FEASIBILITY_EXPERIMENT_V1.md`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.domain.features.dataset.rows import HistoricalFeatureSnapshotKey
from sports_intelligence.domain.retrieval.availability_exact import (
    AvailabilityAwareHistoricalRetriever,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
    RetrievalProjectionKind,
)
from sports_intelligence.domain.retrieval.projection.reconstruct import (
    candidate_row_from_payload,
)
from sports_intelligence.domain.retrieval.query import HistoricalRetrievalQuery
from sports_intelligence.domain.retrieval.timepoint import GRID_SEQUENCE, GRID_STOPPAGE
from sports_intelligence.ports.retrieval_projection import CandidateUniverseFilter


@final
@dataclass(slots=True)
class ProjectedTimings:
    """Onde o tempo foi. Quatro parcelas, e a soma NÃO é o total.

    A DIFERENÇA É DELIBERADAMENTE VISÍVEL. O total é medido de ponta a ponta e
    as parcelas por dentro; o que sobra é o que ninguém instrumentou, e fazer o
    total ser a soma das partes esconderia exatamente esse custo.
    """

    resolve_ms: float = 0.0
    lookup_ms: float = 0.0
    decode_ms: float = 0.0
    compute_ms: float = 0.0
    total_ms: float = 0.0

    def as_mapping(self) -> Mapping[str, float]:
        return {
            "compute_ms": self.compute_ms,
            "decode_ms": self.decode_ms,
            "lookup_ms": self.lookup_ms,
            "resolve_ms": self.resolve_ms,
            "total_ms": self.total_ms,
            "unaccounted_ms": self.total_ms
            - (self.resolve_ms + self.lookup_ms + self.decode_ms + self.compute_ms),
        }


@final
@dataclass(frozen=True, slots=True)
class ProjectedStateOutcome:
    """O resultado exato, mais o que custou obtê-lo."""

    result: AvailabilityAwareRetrievalResult
    universe_rows: int
    timings: ProjectedTimings


def universe_filter_for(
    *, competition: str, position: Any, exclude_match_id: str
) -> CandidateUniverseFilter:
    """O filtro do universo a partir da posição da query.

    O ACRÉSCIMO E O DESEMPATE VÊM DAS CONSTANTES DA GRADE, e não do
    `GridTimePoint`: a grade os fixa, e o tipo não os carrega justamente porque
    eles não variam. Gravá-los assim mesmo é o que permite escrever a conjunção
    INTEIRA de `EXACT_MATCH_TIME_POINT` no `WHERE`.
    """
    return CandidateUniverseFilter(
        competition=competition,
        period=position.period.value,
        minute=position.minute,
        stoppage=GRID_STOPPAGE,
        tie_break=str(GRID_SEQUENCE),
        exclude_match_id=exclude_match_id,
    )


@final
@dataclass(frozen=True, slots=True)
class RetrieveProjectedStateHistoricalNeighbors:
    """O top-K de ESTADO lendo o universo do PostgreSQL, com cálculo exato."""

    aware: Any
    reader: Any

    async def execute(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        candidate_policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
    ) -> ProjectedStateOutcome:
        inicio = time.perf_counter()
        tempos = ProjectedTimings()

        # ---- 1. a projeção serve esta query? FAIL CLOSED antes de tudo ----
        projection_version.assert_queryable()
        projection_version.assert_serves(
            dataset_version_id=version_id,
            plan_fingerprint=projection_version.binding.normalization_plan_fingerprint,
            artifact_set_fingerprint=projection_version.binding.artifact_set_fingerprint,
            kind=RetrievalProjectionKind.STATE,
        )

        # ---- 2. a resolução, pelo caminho de sempre ------------------------
        marca = time.perf_counter()
        contexto = await self.aware.resolve(version_id=version_id, key=key)
        tempos.resolve_ms = (time.perf_counter() - marca) * 1000
        resolucao = contexto.resolution
        instantaneo = resolucao.snapshot

        retriever = AvailabilityAwareHistoricalRetriever(
            policy=candidate_policy,
            profile=resolucao.profile,
            distance=contexto.distance,
        )
        # A RECUSA DA QUERY VEM ANTES DA LEITURA — a lição do PR-06.2, aplicada
        # de novo: uma query sem cobertura não pode pagar o universo.
        retriever.assert_query_admissible(instantaneo)

        # ---- 3. o universo EXATO, numa consulta ---------------------------
        universo = universe_filter_for(
            competition=resolucao.competition,
            position=instantaneo.position,
            exclude_match_id=instantaneo.key.match_key,
        )
        marca = time.perf_counter()
        projetados = await self.reader.load_state_universe(
            projection_version=projection_version,
            universe=universo,
            axis_keys=projection_version.axis_keys,
        )
        tempos.lookup_ms = (time.perf_counter() - marca) * 1000

        # ---- 4. a reconstrução --------------------------------------------
        marca = time.perf_counter()
        candidatos = [
            candidate_row_from_payload(
                p.payload,
                feature_keys=resolucao.profile.feature_keys,
                match_id=p.match_id,
                competition=p.competition,
                season=p.season,
                position=instantaneo.position,
                semantic_key=p.semantic_key,
            )
            for p in projetados
        ]
        tempos.decode_ms = (time.perf_counter() - marca) * 1000

        # ---- 5. o CÁLCULO EXATO, pelo retriever que já existe --------------
        marca = time.perf_counter()
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=resolucao.version.id,
            dataset_name=resolucao.dataset_name,
            dataset_version=resolucao.version_text,
            representation=resolucao.version.representation,
            key=key,
            k=k,
            policy=candidate_policy,
            profile=resolucao.profile.base,
        )
        resultado = retriever.retrieve(
            query=pedido,
            snapshot=instantaneo,
            candidates=candidatos,
            reference_content_fingerprint=self.aware.exact.reference_fingerprint(resolucao.version),
        )
        tempos.compute_ms = (time.perf_counter() - marca) * 1000
        tempos.total_ms = (time.perf_counter() - inicio) * 1000

        return ProjectedStateOutcome(
            result=resultado, universe_rows=len(projetados), timings=tempos
        )
