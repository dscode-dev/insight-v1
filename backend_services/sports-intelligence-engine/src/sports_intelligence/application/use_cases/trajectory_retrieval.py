"""O caso de uso da recuperação de trajetórias — e a comparação lado a lado.

A SEQUÊNCIA REUSA OS CINCO PRIMEIROS PASSOS DO PR-06.1 e acrescenta três:

    1 a 5   versão READY, conjunto declarado, plano conferido, query carregada,
            perfil resolvido            `resolve_base` — o MESMO código
    6       a GRADE do dataset          da versão CRUA de origem, e conferida
    7       a janela de lookback        resolvida sobre a âncora
    8       as trajetórias              âncora e lookback, em UMA varredura

**A GRADE VEM DO DATASET, e não do chamador.** Ela é lida da versão crua que
originou a normalizada, e a política de janela a confere: uma grade que não
anda de minuto em minuto produz `UNSUPPORTED_TRAJECTORY_GRID`, e não slots
inventados. Deixar o chamador declará-la faria a linhagem ser uma afirmação em
vez de um fato.

**E O UNIVERSO É O MESMO.** Os candidatos saem da MESMA partição, sob a MESMA
política, no MESMO instante de âncora — `CandidateUniverse_06.3 =
CandidateUniverse_06.2`. A trajetória muda COMO os candidatos são comparados, e
não QUEM é candidato.

**NÃO HÁ SCORE COMBINADO** (§4, §147, §258). `CompareStateAndTrajectory` roda os
dois e os apresenta lado a lado. Ele não soma, não pondera e não devolve
`D_total`: a combinação exige `alfa` e `beta`, e não há rótulo de verdade com
que calibrá-los antes do PR-06.5.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.application.use_cases.availability_retrieval import (
    RetrieveAvailabilityAwareHistoricalNeighbors,
)
from sports_intelligence.application.use_cases.retrieval import (
    RetrievalResolution,
    RetrieveExactHistoricalNeighbors,
)
from sports_intelligence.domain.features.dataset.grid import SnapshotGridPolicy
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.coverage import (
    QueryInsufficientCoverageError,
)
from sports_intelligence.domain.retrieval.query import HistoricalRetrievalQuery
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory import (
    TrajectoryRepresentation,
    assemble_trajectory,
    build_representation,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    QueryInsufficientTrajectoryEvidenceError,
    TrajectoryCoveragePolicy,
)
from sports_intelligence.domain.retrieval.trajectory_distance import (
    TrajectoryDistanceDefinition,
)
from sports_intelligence.domain.retrieval.trajectory_exact import (
    ExactTrajectoryRetriever,
    TrajectoryCandidate,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    DEFAULT_TRAJECTORY_PROFILE,
    ResolvedTrajectoryProfile,
    TrajectoryRetrievalProfile,
)
from sports_intelligence.domain.retrieval.trajectory_result import (
    TrajectoryRetrievalResult,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    ResolvedSlot,
    TrajectoryNotApplicableError,
)
from sports_intelligence.domain.shared.errors import NotFoundError
from sports_intelligence.ports.object_store.trajectory import (
    HistoricalTrajectorySourcePort,
)
from sports_intelligence.ports.repositories.feature_dataset import (
    HistoricalFeatureDatasetRepositoryPort,
)


@final
@dataclass(frozen=True, slots=True)
class TrajectoryContext:
    """A resolução, a grade, a janela e a trajetória da query."""

    resolution: RetrievalResolution
    grid: SnapshotGridPolicy
    profile: ResolvedTrajectoryProfile
    distance: TrajectoryDistanceDefinition
    slots: tuple[ResolvedSlot, ...]
    representation: TrajectoryRepresentation

    @property
    def competition(self) -> str:
        return self.resolution.competition

    @property
    def anchor(self) -> GridTimePoint:
        return self.resolution.snapshot.position

    @property
    def targets(self) -> tuple[GridTimePoint, ...]:
        return tuple(s.target for s in self.slots if s.target is not None)

    def summary(self) -> Mapping[str, Any]:
        return {
            **self.resolution.summary(),
            "anchor": self.anchor.text,
            "cell_count": self.profile.cell_count,
            "coverage_policy_fingerprint": self.distance.coverage_policy.fingerprint,
            "distance_fingerprint": self.distance.fingerprint,
            "grid_name": self.grid.name,
            "horizon_count": self.profile.horizon_count,
            "horizons": list(self.profile.horizons),
            "structural_horizons": len(self.targets),
            "trajectory_fingerprint": self.representation.fingerprint,
            "trajectory_profile_fingerprint": self.profile.fingerprint,
            "usable_cells": self.representation.usable_count,
            "window_fingerprint": self.profile.profile.window.fingerprint,
        }


@final
@dataclass(frozen=True, slots=True)
class RetrieveExactHistoricalTrajectories:
    """O top-K de trajetória de uma query de AVALIAÇÃO."""

    exact: RetrieveExactHistoricalNeighbors
    raw_datasets: HistoricalFeatureDatasetRepositoryPort
    trajectory_source: HistoricalTrajectorySourcePort
    coverage_policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE
    profile: TrajectoryRetrievalProfile = DEFAULT_TRAJECTORY_PROFILE

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
        coverage_policy: TrajectoryCoveragePolicy | None = None,
        batch_rows: int | None = None,
    ) -> TrajectoryRetrievalResult:
        contexto = await self.resolve(
            version_id=version_id, key=key, coverage_policy=coverage_policy
        )
        retriever = ExactTrajectoryRetriever(
            policy=policy, profile=contexto.profile, distance=contexto.distance
        )
        # A RECUSA DA QUERY VEM ANTES DA LEITURA (§82), e a lição é a do
        # PR-06.2: `candidates=await …` como argumento avalia a varredura
        # primeiro, e uma query sem história recente pagaria o universo
        # inteiro. No começo de cada período essa recusa é o caminho NORMAL.
        retriever.assert_query_admissible(contexto.representation)
        candidatos = await self._candidatos(contexto, batch_rows)
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=contexto.resolution.version.id,
            dataset_name=contexto.resolution.dataset_name,
            dataset_version=contexto.resolution.version_text,
            representation=contexto.resolution.version.representation,
            key=key,
            k=k,
            policy=policy,
            profile=self.profile.base,
        )
        return retriever.retrieve(
            query=pedido,
            snapshot=contexto.resolution.snapshot,
            query_representation=contexto.representation,
            candidates=candidatos,
            reference_content_fingerprint=self.exact.reference_fingerprint(
                contexto.resolution.version
            ),
        )

    # ------------------------------------------------------------ a resolução --

    async def resolve(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        coverage_policy: TrajectoryCoveragePolicy | None = None,
    ) -> TrajectoryContext:
        """Versão, grade, janela e a trajetória da query — sem varrer candidato.

        A ORDEM É A DO CABEÇALHO. A grade é conferida ANTES de a janela ser
        resolvida, e a aplicabilidade da âncora antes de qualquer leitura de
        lookback: uma query em `PRE_MATCH` não lê linha nenhuma.
        """
        base = await self.exact.resolve_base(
            version_id=version_id, key=key, profile=self.profile.base
        )
        grade = await self._grade(base)
        janela = self.profile.window
        janela.assert_supports(grade)
        ancora = base.snapshot.position
        if not janela.is_applicable(ancora):
            raise TrajectoryNotApplicableError(anchor=ancora.text, period=ancora.period.value)

        resolvido = self.profile.resolve(base.profile)
        slots = janela.resolve(ancora, grid=grade)
        alvos = [s.target for s in slots if s.target is not None]
        linhas = await self.trajectory_source.load_query_trajectory_rows(
            dataset_name=base.dataset_name,
            version=base.version_text,
            key=key,
            targets=alvos,
            feature_keys=list(resolvido.feature_keys),
        )
        trajetoria = assemble_trajectory(
            policy=janela,
            resolved=slots,
            anchor_key=key,
            match_key=key.match_key,
            competition=base.competition,
            anchor_position=ancora,
            anchor_row_digest=base.snapshot.row_digest,
            rows=linhas,
        )
        representacao = build_representation(
            trajectory=trajetoria,
            feature_keys=resolvido.feature_keys,
            horizons=resolvido.horizons,
            profile_fingerprint=resolvido.fingerprint,
            anchor_values=base.snapshot.values,
            anchor_availabilities=base.snapshot.availabilities,
            rows=linhas,
        )
        return TrajectoryContext(
            resolution=base,
            grid=grade,
            profile=resolvido,
            distance=TrajectoryDistanceDefinition(
                profile=resolvido,
                coverage_policy=coverage_policy or self.coverage_policy,
            ),
            slots=slots,
            representation=representacao,
        )

    async def _grade(self, base: RetrievalResolution) -> SnapshotGridPolicy:
        """A grade DA VERSÃO CRUA de origem — a linhagem, e não uma afirmação.

        ELA NÃO VEM DO CHAMADOR (§27). «Este dataset tem grade de minuto» é um
        fato do dataset, e recebê-lo por parâmetro faria a conferência de
        compatibilidade validar o que o chamador disse em vez do que o dataset
        é — e um chamador distraído autorizaria lookback numa grade de cinco
        cortes.
        """
        crua = await self.raw_datasets.version_by_id(base.version.source_version_id)
        if crua is None:
            raise NotFoundError(
                f"a versão crua {base.version.source_version_id} não existe: sem ela "
                "não há como saber sob qual grade este dataset foi construído, e a "
                "trajetória não pode adivinhar o passo do lookback",
                context={"source_version_id": base.version.source_version_id},
            )
        return crua.spec.grid

    async def _candidatos(
        self, contexto: TrajectoryContext, batch_rows: int | None
    ) -> list[TrajectoryCandidate]:
        """As trajetórias dos candidatos, montadas em LOTE.

        UMA VARREDURA POR PARTIÇÃO (§128, §245). O leitor devolve âncora e
        lookback já agrupados por partida; aqui só resta montar a trajetória e
        os deslocamentos de cada um.
        """
        resolvidos = contexto.slots
        montados: list[TrajectoryCandidate] = []
        async for lote in self.trajectory_source.stream_candidate_trajectories(
            dataset_name=contexto.resolution.dataset_name,
            version=contexto.resolution.version_text,
            competition=contexto.competition,
            anchor=contexto.anchor,
            targets=list(contexto.targets),
            feature_keys=list(contexto.profile.feature_keys),
            batch_rows=batch_rows or 2_000,
        ):
            for cru in lote:
                trajetoria = assemble_trajectory(
                    policy=contexto.profile.profile.window,
                    resolved=resolvidos,
                    anchor_key=cru.anchor_key,
                    match_key=cru.match_id,
                    competition=cru.competition,
                    anchor_position=cru.anchor_position,
                    anchor_row_digest=cru.anchor_row_digest,
                    rows=cru.lookback,
                )
                montados.append(
                    TrajectoryCandidate(
                        match_id=cru.match_id,
                        season=cru.season,
                        representation_fingerprint=cru.representation_fingerprint,
                        representation=build_representation(
                            trajectory=trajetoria,
                            feature_keys=contexto.profile.feature_keys,
                            horizons=contexto.profile.horizons,
                            profile_fingerprint=contexto.profile.fingerprint,
                            anchor_values=cru.anchor_values,
                            anchor_availabilities=cru.anchor_availabilities,
                            rows=cru.lookback,
                        ),
                    )
                )
        return montados


@final
@dataclass(frozen=True, slots=True)
class DescribeTrajectory:
    """A janela e a trajetória de uma query, sem calcular distância nenhuma.

    ELE EXISTE PARA A CLI E PARA O BENCHMARK. «Quais horizontes esta âncora
    tem?» é a pergunta que se faz antes de pagar a varredura, e respondê-la
    rodando a recuperação faria o diagnóstico custar o resultado.
    """

    retriever: RetrieveExactHistoricalTrajectories

    async def execute(
        self, *, version_id: str, key: HistoricalFeatureSnapshotKey
    ) -> Mapping[str, Any]:
        from sports_intelligence.domain.retrieval.trajectory_window import slot_counts

        contexto = await self.retriever.resolve(version_id=version_id, key=key)
        cobertura = contexto.distance.assess(contexto.representation, contexto.representation)
        return {
            **contexto.summary(),
            "query_usable_horizons": cobertura.query_usable_horizons,
            "query_meets_floor": cobertura.meets_query_floor,
            "slots": [str(s) for s in contexto.slots],
            **slot_counts(contexto.slots),
        }


@final
@dataclass(frozen=True, slots=True)
class StateAndTrajectory:
    """Os dois resultados da mesma query, LADO A LADO — e nunca somados.

    NÃO HÁ `D_total` AQUI, e a ausência é a decisão (§147, §258). Este contrato
    apresenta; ele não combina.
    """

    key: HistoricalFeatureSnapshotKey
    anchor: str
    competition: str
    state: AvailabilityAwareRetrievalResult | None
    trajectory: TrajectoryRetrievalResult | None
    state_rejected: bool = False
    trajectory_rejected: bool = False
    trajectory_not_applicable: bool = False

    @property
    def top_k_overlap(self) -> float | None:
        """`|TopK_state ∩ TopK_trajectory| / |TopK_state|` (§148, §195).

        DIAGNÓSTICO, E NUNCA MÉTRICA DE CORREÇÃO (§196). Estado e trajetória
        medem conceitos DIFERENTES: uma sobreposição baixa pode ser exatamente
        o sinal desejado — os jogos mais parecidos agora não são os que se
        moveram parecido.
        """
        if self.state is None or self.trajectory is None or not self.state.neighbors:
            return None
        do_estado = {v.key.text for v in self.state.neighbors}
        da_trajetoria = {v.anchor_key.text for v in self.trajectory.neighbors}
        return len(do_estado & da_trajetoria) / len(do_estado)

    def summary(self) -> Mapping[str, Any]:
        return {
            "anchor": self.anchor,
            "competition": self.competition,
            "key": self.key.text,
            "state_eligible": None if self.state is None else self.state.coverage_eligible_count,
            "state_rejected": self.state_rejected,
            "state_returned": None if self.state is None else self.state.returned_k,
            "top_k_overlap": self.top_k_overlap,
            "trajectory_eligible": (
                None if self.trajectory is None else self.trajectory.trajectory_eligible_count
            ),
            "trajectory_not_applicable": self.trajectory_not_applicable,
            "trajectory_rejected": self.trajectory_rejected,
            "trajectory_returned": (
                None if self.trajectory is None else self.trajectory.returned_k
            ),
            "universe": (
                self.state.universe_count
                if self.state is not None
                else (self.trajectory.universe_count if self.trajectory is not None else 0)
            ),
        }


@final
@dataclass(frozen=True, slots=True)
class CompareStateAndTrajectory:
    """Estado e trajetória sobre a mesma query — apresentados, não combinados.

    ELE REUSA OS DOIS CASOS DE USO e não reimplementa nenhum (§146). As recusas
    de cada lado são REGISTRADAS, e não propagadas: uma query aplicável ao
    estado e não à trajetória — o começo de um período — é exatamente o caso
    que esta ferramenta existe para contar.
    """

    state: RetrieveAvailabilityAwareHistoricalNeighbors
    trajectory: RetrieveExactHistoricalTrajectories

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
    ) -> StateAndTrajectory:
        do_estado: AvailabilityAwareRetrievalResult | None = None
        estado_recusado = False
        try:
            do_estado = await self.state.execute(version_id=version_id, key=key, k=k, policy=policy)
        except QueryInsufficientCoverageError:
            estado_recusado = True

        da_trajetoria: TrajectoryRetrievalResult | None = None
        trajetoria_recusada = False
        nao_aplicavel = False
        try:
            da_trajetoria = await self.trajectory.execute(
                version_id=version_id, key=key, k=k, policy=policy
            )
        except TrajectoryNotApplicableError:
            nao_aplicavel = True
        except QueryInsufficientTrajectoryEvidenceError:
            trajetoria_recusada = True

        ancora = ""
        competicao = ""
        if do_estado is not None:
            competicao = do_estado.competition
        if da_trajetoria is not None:
            ancora = da_trajetoria.query_anchor_position.text
            competicao = da_trajetoria.competition
        return StateAndTrajectory(
            key=key,
            anchor=ancora,
            competition=competicao,
            state=do_estado,
            trajectory=da_trajetoria,
            state_rejected=estado_recusado,
            trajectory_rejected=trajetoria_recusada,
            trajectory_not_applicable=nao_aplicavel,
        )


def trajectory_context_summary(contexto: TrajectoryContext) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    return [
        f"âncora        {contexto.anchor.text}",
        f"grade         {contexto.grid.name}",
        f"janela        {contexto.profile.profile.window.identity}",
        f"horizontes    {list(contexto.profile.horizons)}",
        f"estruturais   {len(contexto.targets)}/{contexto.profile.horizon_count}",
        f"células       {contexto.representation.usable_count}/{contexto.profile.cell_count}",
        *(f"  {s}" for s in contexto.slots),
    ]
