"""Montar as projeções REAIS sobre o corpus real, e comparar com o oráculo.

ELE É O CENTRO DA VALIDAÇÃO DO PR-06.4. O que ele monta não é um duplo: é a
projeção de verdade, construída pelo caso de uso de verdade, a partir do
dataset normalizado que o pipeline de verdade publicou.

    corpus real -> dataset cru -> ajuste -> normalizado READY
                                                  |
                                                  v
                                          projeção STATE + TRAJETÓRIA
                                                  |
                                                  v
                                   comparação contra o oráculo Parquet
"""

from __future__ import annotations

from typing import Any

from sports_intelligence.adapters.postgres.retrieval_projection import (
    PostgresRetrievalProjectionReader,
    PostgresRetrievalProjectionRepository,
    PostgresRetrievalProjectionWriter,
)
from sports_intelligence.application.use_cases.projected_retrieval import (
    RetrieveProjectedStateHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.projected_trajectory_retrieval import (
    RetrieveProjectedTrajectoryHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.projection_build import (
    BuildStateProjection,
    BuildTrajectoryProjection,
    ValidateAndPublishProjection,
)
from sports_intelligence.domain.features.normalized.plan import normalization_plan_v1
from sports_intelligence.domain.retrieval.candidate_policy import DEFAULT_CANDIDATE_POLICY
from sports_intelligence.domain.retrieval.projection.contract import (
    RetrievalProjectionBinding,
)
from sports_intelligence.domain.retrieval.projection.payload import (
    EXACT_FLOAT64_LE_PAYLOAD_V1,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    DEFAULT_TRAJECTORY_PROFILE,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    DEFAULT_TRAJECTORY_WINDOW,
)


async def montar_projecoes(dados: dict[str, Any], database: Any) -> dict[str, Any]:
    """As duas projeções, construídas e PUBLICADAS pelo caminho real."""
    versao = dados["versao_n"]
    conteiner = dados["conteiner"]
    plano = normalization_plan_v1()
    eixos = plano.robust_keys

    repo = PostgresRetrievalProjectionRepository(database)
    escritor = PostgresRetrievalProjectionWriter(database)
    leitor = PostgresRetrievalProjectionReader(database)

    referencia = conteiner.retrieve.reference_fingerprint(versao)
    amarra_comum = {
        "source_dataset_version_id": versao.id,
        "source_dataset_version": str(versao.version),
        "source_reference_fingerprint": referencia,
        "normalization_plan_fingerprint": plano.fingerprint,
        "artifact_set_fingerprint": versao.artifact_set_fingerprint
        if hasattr(versao, "artifact_set_fingerprint")
        else referencia,
        "candidate_policy_fingerprint": DEFAULT_CANDIDATE_POLICY.fingerprint,
        "exact_payload_encoding": EXACT_FLOAT64_LE_PAYLOAD_V1,
    }

    # ---- ESTADO --------------------------------------------------------
    construtor = BuildStateProjection(source=conteiner.source, repository=repo, writer=escritor)
    resultado_estado = await construtor.execute(
        projection_name="e2e-state",
        dataset_name="match-state-normalized",
        version_id=versao.id,
        version_text=str(versao.version),
        binding=RetrievalProjectionBinding(**amarra_comum),
        axis_keys=eixos,
    )
    publicador = ValidateAndPublishProjection(repository=repo, reader=leitor)
    versao_estado = await publicador.execute(
        outcome=resultado_estado, expected_rows=resultado_estado.rows_written
    )

    # ---- TRAJETÓRIA ----------------------------------------------------
    perfil = DEFAULT_TRAJECTORY_PROFILE
    construtor_t = BuildTrajectoryProjection(
        source=conteiner.source,
        repository=repo,
        writer=escritor,
        window=DEFAULT_TRAJECTORY_WINDOW,
        grid=dados.get("grade") or _grade_do(conteiner, versao),
    )
    resultado_traj = await construtor_t.execute(
        projection_name="e2e-trajectory",
        dataset_name="match-state-normalized",
        version_id=versao.id,
        version_text=str(versao.version),
        binding=RetrievalProjectionBinding(
            **amarra_comum,
            trajectory_window_fingerprint=DEFAULT_TRAJECTORY_WINDOW.fingerprint,
            trajectory_profile_fingerprint=perfil.fingerprint,
            trajectory_coverage_fingerprint=DEFAULT_TRAJECTORY_COVERAGE.fingerprint,
        ),
        axis_keys=eixos,
        horizons=DEFAULT_TRAJECTORY_WINDOW.horizons,
        profile_fingerprint=perfil.fingerprint,
    )
    versao_traj = await publicador.execute(
        outcome=resultado_traj, expected_rows=resultado_traj.rows_written
    )

    projetado = RetrieveProjectedStateHistoricalNeighbors(
        aware=conteiner.retrieve_aware, reader=leitor
    )
    projetado_t = RetrieveProjectedTrajectoryHistoricalNeighbors(
        trajectory=conteiner.retrieve_trajectory, reader=leitor
    )
    return {
        "repo": repo,
        "reader": leitor,
        "state_version": versao_estado,
        "state_build": resultado_estado,
        "trajectory_version": versao_traj,
        "trajectory_build": resultado_traj,
        "projected_state": projetado,
        "projected_trajectory": projetado_t,
    }


def _grade_do(conteiner: Any, versao: Any) -> Any:
    from sports_intelligence.domain.features.dataset.grid import DEFAULT_SNAPSHOT_GRID

    return DEFAULT_SNAPSHOT_GRID
