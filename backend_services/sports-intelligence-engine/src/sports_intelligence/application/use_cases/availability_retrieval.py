"""O caso de uso da recuperação ciente de disponibilidade — e a comparação.

DOIS CASOS DE USO, e o segundo é a razão de o primeiro ser interpretável:

    RetrieveAvailabilityAwareHistoricalNeighbors   o top-K sob o piso e a
                                                   penalidade
    CompareExactRetrievalPolicies                  o MESMO universo sob as
                                                   duas políticas, lado a lado

A COMPARAÇÃO NÃO É LUXO. «O PR-06.2 recupera mais candidatos» é uma afirmação
sobre uma diferença, e uma diferença precisa dos dois lados medidos sobre a
MESMA query, o MESMO universo e os MESMOS eixos. Rodar os dois em execuções
separadas e comparar números de relatórios diferentes deixaria a diferença
atribuível a qualquer coisa.

OS CINCO PRIMEIROS PASSOS SÃO OS DO PR-06.1, e são literalmente o mesmo código
— `resolve_base` e `candidates`. Isso não é economia: é o que garante que o
universo dos dois lados é bit a bit o mesmo, que é a premissa do §5 e a
condição para o §6 ser verificável.

O QUE MUDA É SÓ A RÉGUA:

    PR-06.1   DistanceDefinition                    caso completo, sem piso
    PR-06.2   AvailabilityAwareDistanceDefinition   piso de cobertura e
                                                    penalidade por ausência
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.application.use_cases.retrieval import (
    RetrievalResolution,
    RetrieveExactHistoricalNeighbors,
)
from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability_distance import (
    AvailabilityAwareDistanceDefinition,
)
from sports_intelligence.domain.retrieval.availability_exact import (
    AvailabilityAwareHistoricalRetriever,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateUniversePolicy,
)
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
    QueryInsufficientCoverageError,
)
from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    DEFAULT_RETRIEVAL_PROFILE,
    RetrievalFeatureProfile,
)
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QueryNotComparableError,
)
from sports_intelligence.domain.retrieval.result import ExactRetrievalResult


@final
@dataclass(frozen=True, slots=True)
class AvailabilityRetrievalContext:
    """A resolução, com a régua ciente de disponibilidade por cima."""

    resolution: RetrievalResolution
    distance: AvailabilityAwareDistanceDefinition

    @property
    def competition(self) -> str:
        return self.resolution.competition

    def summary(self) -> Mapping[str, Any]:
        return {
            **self.resolution.summary(),
            "coverage_policy_fingerprint": self.distance.coverage_policy.fingerprint,
            "distance_fingerprint": self.distance.fingerprint,
            "minimum_shared_axes": self.distance.coverage_policy.minimum_shared_axes,
            "missing_penalty": self.distance.missing_penalty,
            "shared_coverage_floor": self.distance.coverage_policy.shared_coverage_floor.text,
        }


@final
@dataclass(frozen=True, slots=True)
class RetrieveAvailabilityAwareHistoricalNeighbors:
    """O top-K ciente de disponibilidade, sobre o universo do PR-06.1."""

    exact: RetrieveExactHistoricalNeighbors
    coverage_policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
        profile: RetrievalFeatureProfile = AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
        coverage_policy: AvailabilityCoveragePolicy | None = None,
        batch_rows: int | None = None,
    ) -> AvailabilityAwareRetrievalResult:
        contexto = await self.resolve(
            version_id=version_id,
            key=key,
            profile=profile,
            coverage_policy=coverage_policy,
        )
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=contexto.resolution.version.id,
            dataset_name=contexto.resolution.dataset_name,
            dataset_version=contexto.resolution.version_text,
            representation=contexto.resolution.version.representation,
            key=key,
            k=k,
            policy=policy,
            profile=profile,
        )
        retriever = AvailabilityAwareHistoricalRetriever(
            policy=policy, profile=contexto.resolution.profile, distance=contexto.distance
        )
        # A RECUSA DA QUERY VEM ANTES DA LEITURA (§86), e a ordem é o ponto.
        #
        # `candidates=await self.exact.candidates(...)` como ARGUMENTO de
        # `retrieve` avalia a leitura primeiro: a query incomparável pagava o
        # universo inteiro em objetos e bytes antes de a recusa acontecer. O
        # benchmark mediu — recusa lendo tanto quanto a varredura completa — e
        # foi assim que o defeito apareceu.
        retriever.assert_query_admissible(contexto.resolution.snapshot)
        candidatos = await self.exact.candidates(contexto.resolution, batch_rows)
        return retriever.retrieve(
            query=pedido,
            snapshot=contexto.resolution.snapshot,
            candidates=candidatos,
            reference_content_fingerprint=self.exact.reference_fingerprint(
                contexto.resolution.version
            ),
        )

    async def resolve(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        profile: RetrievalFeatureProfile = AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
        coverage_policy: AvailabilityCoveragePolicy | None = None,
    ) -> AvailabilityRetrievalContext:
        """A resolução e a régua, sem varrer candidato nenhum."""
        base = await self.exact.resolve_base(version_id=version_id, key=key, profile=profile)
        return AvailabilityRetrievalContext(
            resolution=base,
            distance=AvailabilityAwareDistanceDefinition(
                profile=base.profile,
                coverage_policy=coverage_policy or self.coverage_policy,
            ),
        )


@final
@dataclass(frozen=True, slots=True)
class PolicyComparison:
    """As duas recuperações da mesma query, e a diferença entre elas.

    `recovery` É UMA CONTAGEM, E O NOME DIZ ISSO (§77). «Quantos candidatos a
    mais receberam distância» não é «quantos vizinhos melhores» — não há
    rótulo com que afirmar a segunda coisa, e não haverá antes do PR-06.5.
    Chamar isso de «ganho de acurácia» seria inventar uma medida.
    """

    key: HistoricalFeatureSnapshotKey
    competition: str
    axis_count: int
    universe_count: int
    complete_case_comparable: int
    availability_aware_eligible: int
    complete_case_returned: int
    availability_aware_returned: int
    top_k_overlap: float | None
    complete_case_keys: tuple[str, ...] = ()
    availability_aware_keys: tuple[str, ...] = ()
    query_available_count: int = 0
    complete_case_rejected: bool = False
    availability_aware_rejected: bool = False

    @property
    def candidate_recovery(self) -> int:
        """Quantos candidatos a MAIS foram medidos. Pode ser negativo."""
        return self.availability_aware_eligible - self.complete_case_comparable

    @property
    def relative_recovery(self) -> float | None:
        """A recuperação como razão do que o caso completo já tinha.

        `None` QUANDO O CASO COMPLETO NÃO TINHA NADA — e esse é justamente o
        caso mais interessante (§155): uma query que não tinha nenhum vizinho
        e passou a ter. Devolver «infinito» ou zero apagaria a distinção.
        """
        if self.complete_case_comparable < 1:
            return None
        return self.candidate_recovery / self.complete_case_comparable

    @property
    def recovered_from_zero(self) -> bool:
        """§62, §155 — a query que não tinha vizinho nenhum e passou a ter."""
        return self.complete_case_returned == 0 and self.availability_aware_returned > 0

    def summary(self) -> Mapping[str, Any]:
        return {
            "availability_aware_eligible": self.availability_aware_eligible,
            "availability_aware_returned": self.availability_aware_returned,
            "axis_count": self.axis_count,
            "candidate_recovery": self.candidate_recovery,
            "competition": self.competition,
            "complete_case_comparable": self.complete_case_comparable,
            "complete_case_returned": self.complete_case_returned,
            "key": self.key.text,
            "query_available_count": self.query_available_count,
            "recovered_from_zero": self.recovered_from_zero,
            "relative_recovery": self.relative_recovery,
            "top_k_overlap": self.top_k_overlap,
            "universe_count": self.universe_count,
        }


@final
@dataclass(frozen=True, slots=True)
class CompareExactRetrievalPolicies:
    """As duas políticas sobre a MESMA query — a ferramenta de diagnóstico.

    ELA REUSA OS DOIS CASOS DE USO e não reimplementa nenhum (§126). O universo
    sai da mesma leitura, e é isso que torna a diferença atribuível à política
    de ausência, e a nada mais.

    AS DUAS RECUSAS SÃO REGISTRADAS, E NÃO PROPAGADAS. Uma query incomparável
    sob o caso completo e comparável sob a cobertura é exatamente o caso que
    esta ferramenta existe para contar — deixar a exceção subir faria o
    diagnóstico parar no primeiro exemplo do fenômeno que ele mede.
    """

    exact: RetrieveExactHistoricalNeighbors
    aware: RetrieveAvailabilityAwareHistoricalNeighbors

    async def execute(
        self,
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy = DEFAULT_CANDIDATE_POLICY,
        batch_rows: int | None = None,
    ) -> PolicyComparison:
        base = await self.exact.resolve_base(
            version_id=version_id, key=key, profile=DEFAULT_RETRIEVAL_PROFILE
        )
        candidatos = await self.exact.candidates(base, batch_rows)

        completo = await self._caso_completo(base, candidatos, k=k, policy=policy)
        ciente = await self._ciente(
            base, candidatos, key=key, k=k, policy=policy, version_id=version_id
        )
        return self._comparar(base, completo, ciente, key=key)

    # ------------------------------------------------------------ os dois --

    async def _caso_completo(
        self,
        base: RetrievalResolution,
        candidatos: list[CandidateRow],
        *,
        k: int,
        policy: CandidateUniversePolicy,
    ) -> ExactRetrievalResult | None:
        from sports_intelligence.domain.retrieval.distance import DistanceDefinition
        from sports_intelligence.domain.retrieval.exact import ExactHistoricalRetriever

        pedido = HistoricalRetrievalQuery(
            dataset_version_id=base.version.id,
            dataset_name=base.dataset_name,
            dataset_version=base.version_text,
            representation=base.version.representation,
            key=base.snapshot.key,
            k=k,
            policy=policy,
            profile=DEFAULT_RETRIEVAL_PROFILE,
        )
        try:
            return ExactHistoricalRetriever(
                policy=policy,
                profile=base.profile,
                distance=DistanceDefinition(profile=base.profile),
            ).retrieve(
                query=pedido,
                snapshot=base.snapshot,
                candidates=candidatos,
                reference_content_fingerprint=self.exact.reference_fingerprint(base.version),
            )
        except QueryNotComparableError:
            return None

    async def _ciente(
        self,
        base: RetrievalResolution,
        candidatos: list[CandidateRow],
        *,
        version_id: str,
        key: HistoricalFeatureSnapshotKey,
        k: int,
        policy: CandidateUniversePolicy,
    ) -> AvailabilityAwareRetrievalResult | None:
        contexto = await self.aware.resolve(version_id=version_id, key=key)
        pedido = HistoricalRetrievalQuery(
            dataset_version_id=base.version.id,
            dataset_name=base.dataset_name,
            dataset_version=base.version_text,
            representation=base.version.representation,
            key=key,
            k=k,
            policy=policy,
            profile=AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
        )
        try:
            return AvailabilityAwareHistoricalRetriever(
                policy=policy,
                profile=contexto.resolution.profile,
                distance=contexto.distance,
            ).retrieve(
                query=pedido,
                snapshot=contexto.resolution.snapshot,
                candidates=candidatos,
                reference_content_fingerprint=self.exact.reference_fingerprint(base.version),
            )
        except QueryInsufficientCoverageError:
            return None

    # ---------------------------------------------------------- a diferença --

    @staticmethod
    def _comparar(
        base: RetrievalResolution,
        completo: ExactRetrievalResult | None,
        ciente: AvailabilityAwareRetrievalResult | None,
        *,
        key: HistoricalFeatureSnapshotKey,
    ) -> PolicyComparison:
        chaves_cc = tuple(v.key.text for v in completo.neighbors) if completo else ()
        chaves_aa = tuple(v.key.text for v in ciente.neighbors) if ciente else ()
        universo = completo.universe_count if completo else (ciente.universe_count if ciente else 0)
        return PolicyComparison(
            key=key,
            competition=base.competition,
            axis_count=base.profile.axis_count,
            universe_count=universo,
            complete_case_comparable=completo.comparable_count if completo else 0,
            availability_aware_eligible=ciente.coverage_eligible_count if ciente else 0,
            complete_case_returned=len(chaves_cc),
            availability_aware_returned=len(chaves_aa),
            top_k_overlap=_sobreposicao(chaves_cc, chaves_aa),
            complete_case_keys=chaves_cc,
            availability_aware_keys=chaves_aa,
            query_available_count=ciente.query_available_count if ciente else 0,
            complete_case_rejected=completo is None,
            availability_aware_rejected=ciente is None,
        )


def _sobreposicao(
    complete_case: tuple[str, ...], availability_aware: tuple[str, ...]
) -> float | None:
    """`|AA ∩ CC| / |CC|` — DIAGNÓSTICO, e nunca métrica de correção (§78).

    ELA NÃO MEDE ACERTO. Uma sobreposição baixa significa que a política de
    ausência trouxe candidatos que o caso completo não podia ver, e isso é o
    comportamento pretendido — não um erro. O número existe para descrever
    QUANTO os dois rankings se afastam, e não para decidir qual está certo.

    `None` QUANDO O CASO COMPLETO NÃO DEVOLVEU NADA: uma razão com denominador
    zero não é zero.
    """
    if not complete_case:
        return None
    return len(set(complete_case) & set(availability_aware)) / len(complete_case)
