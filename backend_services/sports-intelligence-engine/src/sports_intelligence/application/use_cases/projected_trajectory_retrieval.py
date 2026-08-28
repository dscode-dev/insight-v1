"""O top-K de TRAJETÓRIA pela projeção — orquestração, e não nova matemática.

O MESMO DESENHO DO ESTADO, com uma diferença que importa: uma trajetória não é
uma linha, e reconstruí-la exige mais que os números.

    resolve a query de trajetória   (o caminho do PR-06.3, intacto)
    lê o universo EXATO             (uma consulta ao PostgreSQL)
    reconstrói a TRAJETÓRIA         (linhagem dos slots + deslocamentos)
    ENTREGA AO `ExactTrajectoryRetriever` QUE JÁ EXISTE

A LINHAGEM É O QUE FAZ A IMPRESSÃO BATER. A impressão da trajetória cobre a
âncora, a política e o digesto de cada slot; sem esses digestos a trajetória
reconstruída teria os mesmos deslocamentos e outra identidade — e a evidência
divergiria do oráculo sem que um único número mudasse.

O PERFIL RESOLVIDO RECORTA O PAYLOAD. A projeção guarda as `3 x 29` células
canônicas; a distância é medida sobre os eixos que a competição resolveu.
`restrict_to_profile` faz o recorte na ORDEM do perfil, e é isso que torna a
representação reconstruída idêntica à que o oráculo montaria do Parquet.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.application.use_cases.projected_retrieval import (
    ProjectedTimings,
    universe_filter_for,
)
from sports_intelligence.domain.features.dataset.rows import HistoricalFeatureSnapshotKey
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.projection.contract import (
    HistoricalRetrievalProjectionVersion,
    RetrievalProjectionKind,
)
from sports_intelligence.domain.retrieval.projection.reconstruct import (
    trajectory_from_lineage,
    trajectory_representation_from_payload,
)
from sports_intelligence.domain.retrieval.query import HistoricalRetrievalQuery
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory_exact import (
    ExactTrajectoryRetriever,
    TrajectoryCandidate,
)
from sports_intelligence.domain.retrieval.trajectory_result import (
    TrajectoryRetrievalResult,
)


@final
@dataclass(frozen=True, slots=True)
class ProjectedTrajectoryOutcome:
    result: TrajectoryRetrievalResult
    universe_rows: int
    timings: ProjectedTimings


@final
@dataclass(frozen=True, slots=True)
class RetrieveProjectedTrajectoryHistoricalNeighbors:
    """O top-K de TRAJETÓRIA lendo o universo do PostgreSQL."""

    trajectory: Any
    reader: Any

    async def execute(
        self,
        *,
        projection_version: HistoricalRetrievalProjectionVersion,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        candidate_policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
    ) -> ProjectedTrajectoryOutcome:
        inicio = time.perf_counter()
        tempos = ProjectedTimings()

        # ---- 1. a projeção serve esta query? FAIL CLOSED antes de tudo ----
        projection_version.assert_queryable()
        projection_version.assert_serves(
            dataset_version_id=version_id,
            plan_fingerprint=projection_version.binding.normalization_plan_fingerprint,
            artifact_set_fingerprint=projection_version.binding.artifact_set_fingerprint,
            kind=RetrievalProjectionKind.TRAJECTORY,
        )

        # ---- 2. a resolução, pelo caminho do PR-06.3 ----------------------
        marca = time.perf_counter()
        contexto = await self.trajectory.resolve(version_id=version_id, key=key)
        tempos.resolve_ms = (time.perf_counter() - marca) * 1000
        resolucao = contexto.resolution
        instantaneo = resolucao.snapshot

        retriever = ExactTrajectoryRetriever(
            policy=candidate_policy,
            profile=contexto.profile,
            distance=contexto.distance,
        )
        # A RECUSA DA QUERY VEM ANTES DA LEITURA — no começo de cada período
        # ela é o caminho NORMAL, e pagá-la com uma varredura seria o defeito
        # que o PR-06.2 já corrigiu uma vez.
        retriever.assert_query_admissible(contexto.representation)

        # ---- 3. o universo EXATO, numa consulta --------------------------
        marca = time.perf_counter()
        projetados = await self.reader.load_trajectory_universe(
            projection_version=projection_version,
            universe=universe_filter_for(
                competition=resolucao.competition,
                position=instantaneo.position,
                exclude_match_id=instantaneo.key.match_key,
            ),
            axis_keys=projection_version.axis_keys,
            horizons=list(contexto.profile.horizons),
        )
        tempos.lookup_ms = (time.perf_counter() - marca) * 1000

        # ---- 4. a reconstrução, COM a linhagem ---------------------------
        marca = time.perf_counter()
        janela = contexto.profile.profile.window
        candidatos: list[TrajectoryCandidate] = []
        for projetado in projetados:
            ancora = _chave(projetado.anchor_key)
            trajetoria = trajectory_from_lineage(
                anchor_key=ancora,
                match_key=projetado.match_id,
                competition=projetado.competition,
                anchor_position=GridTimePoint.from_columns(
                    period=instantaneo.position.period.value,
                    minute=instantaneo.position.minute,
                ),
                anchor_row_digest=projetado.payload.anchor_row_digest,
                policy_fingerprint=janela.fingerprint,
                policy_identity=janela.identity,
                slot_lineage=projetado.slot_lineage,
            )
            candidatos.append(
                TrajectoryCandidate(
                    match_id=projetado.match_id,
                    season=projetado.season,
                    representation_fingerprint=instantaneo.representation_fingerprint,
                    representation=trajectory_representation_from_payload(
                        projetado.payload,
                        trajectory=trajetoria,
                        feature_keys=contexto.profile.feature_keys,
                        profile_fingerprint=contexto.profile.fingerprint,
                    ),
                )
            )
        tempos.decode_ms = (time.perf_counter() - marca) * 1000

        # ---- 5. o CÁLCULO EXATO, pelo retriever que já existe -------------
        marca = time.perf_counter()
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=resolucao.version.id,
            dataset_name=resolucao.dataset_name,
            dataset_version=resolucao.version_text,
            representation=resolucao.version.representation,
            key=key,
            k=k,
            policy=candidate_policy,
            profile=self.trajectory.profile.base,
        )
        resultado = retriever.retrieve(
            query=pedido,
            snapshot=instantaneo,
            query_representation=contexto.representation,
            candidates=candidatos,
            reference_content_fingerprint=self.trajectory.exact.reference_fingerprint(
                resolucao.version
            ),
        )
        tempos.compute_ms = (time.perf_counter() - marca) * 1000
        tempos.total_ms = (time.perf_counter() - inicio) * 1000

        return ProjectedTrajectoryOutcome(
            result=resultado, universe_rows=len(projetados), timings=tempos
        )


def _chave(texto: str) -> HistoricalFeatureSnapshotKey:
    match_key, _, indice = texto.rpartition("#")
    return HistoricalFeatureSnapshotKey(match_key=match_key, grid_index=int(indice))
