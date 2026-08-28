"""A varredura exata de trajetórias — exaustiva, e com a memória presa ao K.

O CAMINHO DE CADA CANDIDATO, e a ordem dos passos é o contrato:

    conferência estrutural   competição, instante da ÂNCORA, mesma partida,
                             representação
    representação            os deslocamentos dele, sobre o espaço FIXO
    cobertura temporal       s, os horizontes evidenciais, e os três pisos
    distância                só se a cobertura admitir
    heap                     só se a distância existir

**O CANDIDATO CHEGA COM A TRAJETÓRIA JÁ MONTADA.** Este módulo não lê nada — o
adaptador entrega âncora e lookback juntos, em lote, e é isso que impede o
padrão `candidato x horizonte` de leituras independentes (§127). A separação
também é o que torna as invariantes testáveis sobre listas em memória.

A MEMÓRIA SEGUE O K, e não o universo (§120):

    durante a varredura   O(lote·|H|·m + K·(1 representação + parcelas))
    no fim                O(K·n) para as contribuições por célula
    nunca                 O(universo · n)

O HEAP INVERTE A QUÁDRUPLA INTEIRA. A ordem é `(D_T, -s, -h, chave)`
ascendente; a inversão é `(-D_T, s, h, chave descendente)`, e cada posição é
invertida separadamente. Uma posição não invertida produz um top-K correto em
conteúdo e errado em ordem exatamente quando há empate no corte do `K` — e há
teste de prefixo com empate deliberado para cada um dos três primeiros
critérios.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.candidate import (
    CandidateUniverseAccumulator,
    CandidateUniverseDescriptor,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    CandidateUniversePolicy,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QuerySnapshot,
)
from sports_intelligence.domain.retrieval.trajectory import TrajectoryRepresentation
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    QueryInsufficientTrajectoryEvidenceError,
    TrajectoryCoverageAssessment,
)
from sports_intelligence.domain.retrieval.trajectory_distance import (
    TrajectoryBreakdown,
    TrajectoryDistanceDefinition,
)
from sports_intelligence.domain.retrieval.trajectory_evidence import (
    build_trajectory_evidence,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    ResolvedTrajectoryProfile,
)
from sports_intelligence.domain.retrieval.trajectory_result import (
    TrajectoryHistoricalNeighbor,
    TrajectoryRetrievalResult,
)
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class TrajectoryCandidate:
    """Um candidato do universo, com a trajetória já montada.

    ELE CARREGA A IDENTIDADE DA ÂNCORA e a representação. A identidade vem da
    linha-âncora — a mesma que o PR-06.1 admitiu no universo —, e a
    representação vem da montagem em lote.
    """

    match_id: str
    season: str
    representation_fingerprint: str
    representation: TrajectoryRepresentation

    @property
    def anchor_key(self) -> HistoricalFeatureSnapshotKey:
        return self.representation.trajectory.anchor_key

    @property
    def competition(self) -> str:
        return self.representation.trajectory.competition

    @property
    def semantic_identity(self) -> str:
        chave = self.representation.trajectory.anchor_key
        return f"{chave.text}:{self.representation.trajectory.anchor_row_digest}"


@final
@dataclass(frozen=True, slots=True)
class _Medido:
    """Um candidato medido, com o mínimo que o `drain` precisa."""

    breakdown: TrajectoryBreakdown
    coverage: TrajectoryCoverageAssessment
    candidate: TrajectoryCandidate

    @property
    def order_key(self) -> tuple[float, int, int, str]:
        """`(D_T, -s, -h, chave)` — a MESMA quádrupla do vizinho."""
        return (
            self.breakdown.value,
            -self.coverage.shared_cells,
            -self.coverage.shared_horizons,
            self.candidate.representation.trajectory.anchor_key.text,
        )


@final
@dataclass(frozen=True, slots=True)
class _ChaveDescendente:
    """Uma chave de texto que compara ao contrário — a terceira cópia.

    ELA REPETE A IDEIA DE `exact.py` E DE `availability_exact.py`, e a decisão
    é a mesma: a chave de ordenação de cada retriever tem um tamanho diferente
    — par, tripla, quádrupla —, e extrair um utilitário comum acoplaria os três
    em troca de cinco linhas. Os dois anteriores são réguas congeladas (§5).
    """

    key: str

    def __lt__(self, other: _ChaveDescendente) -> bool:
        return self.key > other.key


@final
class _TopK:
    """O heap limitado, sobre a quádrupla invertida."""

    __slots__ = ("_heap", "_k", "_medidos")

    def __init__(self, k: int) -> None:
        if k < 1:
            raise ValidationError(f"top-K com K = {k}")
        self._k = k
        self._heap: list[tuple[float, int, int, _ChaveDescendente, _Medido]] = []
        self._medidos = 0

    def offer(self, item: _Medido) -> None:
        distancia, menos_celulas, menos_horizontes, chave = item.order_key
        # A INVERSÃO É POSIÇÃO A POSIÇÃO — ver o cabeçalho do módulo.
        entrada = (
            -distancia,
            -menos_celulas,
            -menos_horizontes,
            _ChaveDescendente(chave),
            item,
        )
        self._medidos += 1
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entrada)
            return
        heapq.heappushpop(self._heap, entrada)

    @property
    def measured(self) -> int:
        return self._medidos

    def drain(self) -> list[_Medido]:
        return sorted((item for *_, item in self._heap), key=lambda m: m.order_key)


@final
@dataclass(frozen=True, slots=True)
class ExactTrajectoryRetriever:
    """A varredura exata de trajetórias. Pura: não lê nada, não escreve nada."""

    policy: CandidateUniversePolicy
    profile: ResolvedTrajectoryProfile
    distance: TrajectoryDistanceDefinition

    def __post_init__(self) -> None:
        if self.distance.profile.fingerprint != self.profile.fingerprint:
            raise ValidationError(
                "a definição de distância percorre outro perfil de trajetória: as "
                "células somadas não seriam as células declaradas",
                context={
                    "distance_profile": self.distance.profile.fingerprint,
                    "profile": self.profile.fingerprint,
                },
            )

    # ------------------------------------------------------------ a guarda --

    def assert_query_admissible(
        self, query_representation: TrajectoryRepresentation
    ) -> TrajectoryCoverageAssessment:
        """A query tem história recente bastante? Devolve a cobertura dela.

        ELA É PÚBLICA E É CHAMADA ANTES DA LEITURA DOS CANDIDATOS (§82). A
        recusa por evidência temporal é o caminho NORMAL no começo de cada
        período — no minuto 47 do segundo tempo só o horizonte de um minuto
        existe —, e ela não pode custar a varredura do universo.

        A COBERTURA DA QUERY É MEDIDA CONTRA ELA MESMA. Não há candidato ainda:
        o que se pergunta é «quantas células a query tem, e em quantos
        horizontes evidenciais» — e a auto-avaliação é a forma exata de
        responder isso com a mesma aritmética que o par vai usar.
        """
        self.distance.coverage_policy.assert_profile_admissible(
            axis_count=self.profile.axis_count, competition=self.profile.competition
        )
        cobertura = self.distance.assess(query_representation, query_representation)
        if not cobertura.meets_query_floor:
            raise QueryInsufficientTrajectoryEvidenceError(
                key=query_representation.trajectory.anchor_key,
                anchor=query_representation.trajectory.anchor_position.text,
                assessment=cobertura,
                policy=self.distance.coverage_policy,
            )
        return cobertura

    # ---------------------------------------------------------- a varredura --

    def retrieve(
        self,
        *,
        query: HistoricalRetrievalQuery,
        snapshot: QuerySnapshot,
        query_representation: TrajectoryRepresentation,
        candidates: Iterable[TrajectoryCandidate],
        reference_content_fingerprint: str,
    ) -> TrajectoryRetrievalResult:
        """O top-K de trajetória, sobre TODO o universo."""
        query.assert_snapshot_matches(snapshot)
        self._conferir_query(snapshot, query_representation)
        cobertura_da_query = self.assert_query_admissible(query_representation)

        universo = CandidateUniverseAccumulator()
        topo = _TopK(query.k)
        sem_trajetoria = 0
        estruturais = 0
        for candidato in candidates:
            self._conferir_alinhamento(candidato, snapshot)
            universo.admit_identity(candidato.semantic_identity)
            motivo = self._estrutural(candidato, snapshot)
            if motivo is not None:
                universo.reject(motivo)
                estruturais += 1
                continue
            cobertura = self.distance.assess(query_representation, candidato.representation)
            motivo_de_cobertura = cobertura.refusal_reason
            if motivo_de_cobertura is not None:
                universo.reject(IneligibilityReason(motivo_de_cobertura))
                sem_trajetoria += 1
                continue
            topo.offer(
                _Medido(
                    breakdown=self.distance.evaluate(
                        query_representation, candidato.representation
                    ),
                    coverage=cobertura,
                    candidate=candidato,
                )
            )

        descritor = universo.finalize(
            policy=self.policy,
            competition=snapshot.competition,
            position=snapshot.position,
            query_key=snapshot.key,
            reference_content_fingerprint=reference_content_fingerprint,
            dataset_version_id=query.dataset_version_id,
            representation_fingerprint=query.representation.fingerprint,
        )
        return self._resultado(
            query=query,
            snapshot=snapshot,
            query_representation=query_representation,
            query_coverage=cobertura_da_query,
            descriptor=descritor,
            topo=topo,
            trajectory_ineligible=sem_trajetoria,
            structural_ineligible=estruturais,
        )

    # ------------------------------------------------------------ as guardas --

    def _conferir_query(
        self, snapshot: QuerySnapshot, representation: TrajectoryRepresentation
    ) -> None:
        if snapshot.competition != self.profile.competition:
            raise ValidationError(
                f"a query é de {snapshot.competition} e o perfil foi resolvido para "
                f"{self.profile.competition}: os eixos e as escalas são de outra liga",
                context={
                    "profile": self.profile.competition,
                    "query": snapshot.competition,
                },
            )
        if representation.trajectory.anchor_key != snapshot.key:
            raise ValidationError(
                f"a trajetória é da âncora {representation.trajectory.anchor_key} e a "
                f"query é {snapshot.key}"
            )
        if representation.trajectory.anchor_row_digest != snapshot.row_digest:
            raise ValidationError(
                "a trajetória foi montada sobre outro conteúdo da mesma chave: o "
                "digesto da âncora não bate com o da linha carregada",
                context={"key": snapshot.key.text},
            )

    def _conferir_alinhamento(
        self, candidate: TrajectoryCandidate, snapshot: QuerySnapshot
    ) -> None:
        """A mesma defesa em profundidade dos dois PRs anteriores."""
        if candidate.competition != snapshot.competition:
            raise ValidationError(
                f"candidato de {candidate.competition} para uma query de "
                f"{snapshot.competition}: a escala é ajustada por competição",
                context={"candidate": candidate.semantic_identity},
            )
        ancora = candidate.representation.trajectory.anchor_position
        if not ancora.aligns_with(snapshot.position):
            raise ValidationError(
                f"candidato ancorado em {ancora.text} para uma query em "
                f"{snapshot.position.text}: sob "
                f"{self.policy.time_alignment.value} a ÂNCORA é EXATA — a trajetória "
                "muda como os candidatos são comparados, e não quem é candidato",
                context={"candidate": ancora.text, "query": snapshot.position.text},
            )

    def _estrutural(
        self, candidate: TrajectoryCandidate, snapshot: QuerySnapshot
    ) -> IneligibilityReason | None:
        """As recusas que NÃO são ausência de evidência temporal."""
        if self.policy.excludes_same_match and candidate.match_id == snapshot.key.match_key:
            return IneligibilityReason.SAME_MATCH
        if candidate.representation_fingerprint != snapshot.representation_fingerprint:
            return IneligibilityReason.REPRESENTATION_MISMATCH
        return None

    # ----------------------------------------------------------- o resultado --

    def _resultado(
        self,
        *,
        query: HistoricalRetrievalQuery,
        snapshot: QuerySnapshot,
        query_representation: TrajectoryRepresentation,
        query_coverage: TrajectoryCoverageAssessment,
        descriptor: CandidateUniverseDescriptor,
        topo: _TopK,
        trajectory_ineligible: int,
        structural_ineligible: int,
    ) -> TrajectoryRetrievalResult:
        janela = self.profile.profile.window.fingerprint
        vizinhos = tuple(
            TrajectoryHistoricalNeighbor(
                rank=posicao,
                anchor_key=item.candidate.representation.trajectory.anchor_key,
                match_id=item.candidate.match_id,
                competition=item.candidate.competition,
                season=item.candidate.season,
                anchor_position=item.candidate.representation.trajectory.anchor_position,
                anchor_row_digest=(item.candidate.representation.trajectory.anchor_row_digest),
                trajectory_fingerprint=item.candidate.representation.fingerprint,
                trajectory_dissimilarity=item.breakdown.value,
                evidence=build_trajectory_evidence(
                    query=query_representation,
                    candidate=item.candidate.representation,
                    coverage=item.coverage,
                    breakdown=item.breakdown,
                    window_policy_fingerprint=janela,
                    trajectory_profile_fingerprint=self.profile.fingerprint,
                    coverage_policy_fingerprint=(self.distance.coverage_policy.fingerprint),
                    distance_definition_fingerprint=self.distance.fingerprint,
                ),
            )
            for posicao, item in enumerate(topo.drain(), start=1)
        )
        return TrajectoryRetrievalResult(
            query_anchor_key=snapshot.key,
            query_anchor_row_digest=snapshot.row_digest,
            query_trajectory_fingerprint=query_representation.fingerprint,
            query_anchor_position=snapshot.position,
            competition=snapshot.competition,
            candidate_policy_fingerprint=self.policy.fingerprint,
            candidate_universe_fingerprint=descriptor.fingerprint,
            window_policy_fingerprint=janela,
            trajectory_profile_fingerprint=self.profile.fingerprint,
            coverage_policy_fingerprint=self.distance.coverage_policy.fingerprint,
            distance_definition_fingerprint=self.distance.fingerprint,
            axis_count=self.profile.axis_count,
            horizon_count=self.profile.horizon_count,
            cell_count=self.profile.cell_count,
            query_usable_cells=query_coverage.query_usable_cells,
            query_usable_horizons=query_coverage.query_usable_horizons,
            requested_k=query.k,
            universe_count=descriptor.candidate_count,
            trajectory_eligible_count=topo.measured,
            trajectory_ineligible_count=trajectory_ineligible,
            structural_ineligible_count=structural_ineligible,
            neighbors=vizinhos,
            ineligible=dict(descriptor.ineligible),
            exhaustive=True,
        )
