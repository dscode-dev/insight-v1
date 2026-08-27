"""A varredura ciente de disponibilidade — exaustiva, e com a memória presa ao K.

O CAMINHO DE CADA CANDIDATO, e a ordem dos passos é o contrato (§64):

    conferência estrutural   competição, instante, mesma partida, representação
    máscara                  quais eixos ele tem, sob o perfil FIXO
    cobertura                s, e os dois pisos
    distância                só se a cobertura admitir
    heap                     só se a distância existir

NENHUM CANDIDATO É PULADO ANTES DA MÁSCARA (§65). A tentação é grande: um
candidato «que parece incompleto» poderia ser descartado sem ler as colunas de
valor, e a varredura ficaria mais barata. Ela ficaria mais barata e a atrição
sairia errada — «quantos candidatos não alcançaram o piso» deixaria de ser uma
contagem exata e passaria a ser uma estimativa de quantos o leitor decidiu
olhar.

A MEMÓRIA SEGUE O K, E NÃO O UNIVERSO (§66). O heap guarda `K` itens; cada item
carrega a linha do candidato e as três parcelas — e NÃO a evidência montada. As
contribuições por eixo são construídas no `drain`, para os `K` sobreviventes:

    durante a varredura   O(lote + K·(1 linha + 4 números))
    no fim                O(K·m) para as contribuições
    nunca                 O(universo · m)

Montar a evidência completa de todo candidato faria a alocação seguir o
universo — que é exatamente o que o §66 proíbe, e o que o teste de duas escalas
mede.

O HEAP INVERTE A TRIPLA INTEIRA. A ordem é `(D, -s, chave)` ascendente; o
`heapq` é de mínimo, e precisamos do PIOR dos `K` melhores no topo. A inversão
é `(-D, s, chave_descendente)`, e cada uma das três posições tem de ser
invertida separadamente:

    -D                  inverte a distância
    s (e não -s)        inverte o desempate por evidência
    chave descendente   inverte o desempate canônico

    UMA POSIÇÃO NÃO INVERTIDA produz um top-K correto em conteúdo e errado em
    ordem exatamente quando há empate no corte do K — e um cenário sem empates
    nunca revela isso. É por esse defeito que existe o teste de prefixo com
    empate deliberado no corte.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass
from typing import final

from sports_intelligence.domain.retrieval.availability import (
    availability_mask,
    shared_mask,
    unselected,
)
from sports_intelligence.domain.retrieval.availability import (
    count as _contar,
)
from sports_intelligence.domain.retrieval.availability_distance import (
    AvailabilityAwareDistanceDefinition,
    DistanceBreakdown,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareNeighbor,
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate import (
    CandidateRow,
    CandidateUniverseAccumulator,
    CandidateUniverseDescriptor,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    CandidateUniversePolicy,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.coverage import (
    CoverageAssessment,
    QueryInsufficientCoverageError,
)
from sports_intelligence.domain.retrieval.evidence import build_evidence
from sports_intelligence.domain.retrieval.profile import ResolvedRetrievalProfile
from sports_intelligence.domain.retrieval.query import (
    HistoricalRetrievalQuery,
    QuerySnapshot,
)
from sports_intelligence.domain.shared.errors import ValidationError


@final
@dataclass(frozen=True, slots=True)
class _Medido:
    """Um candidato medido, com o mínimo que o `drain` precisa.

    ELE NÃO CARREGA A EVIDÊNCIA MONTADA. Ver o cabeçalho: a evidência é
    construída no fim, para quem sobreviveu.
    """

    breakdown: DistanceBreakdown
    coverage: CoverageAssessment
    row: CandidateRow
    candidate_mask: tuple[bool, ...]
    shared: tuple[bool, ...]

    @property
    def order_key(self) -> tuple[float, int, str]:
        """`(D, -s, chave)` — a MESMA tripla do vizinho, ascendente."""
        return (
            self.breakdown.value,
            -self.coverage.shared_count,
            self.row.key.text,
        )


@final
@dataclass(frozen=True, slots=True)
class _ChaveDescendente:
    """Uma chave de texto que compara ao contrário.

    ELA REPETE A IDEIA DE `exact.py` E NÃO A COMPARTILHA, e a decisão é
    deliberada: a chave de ordenação de lá é um par e a daqui é uma tripla, e
    extrair um utilitário comum acoplaria o oráculo do PR-06.1 a um módulo
    novo em troca de cinco linhas. O PR-06.1 fica intacto (§4).
    """

    key: str

    def __lt__(self, other: _ChaveDescendente) -> bool:
        return self.key > other.key


@final
class _TopK:
    """O heap limitado, sobre a tripla invertida."""

    __slots__ = ("_heap", "_k", "_medidos")

    def __init__(self, k: int) -> None:
        if k < 1:
            raise ValidationError(f"top-K com K = {k}")
        self._k = k
        self._heap: list[tuple[float, int, _ChaveDescendente, _Medido]] = []
        self._medidos = 0

    def offer(self, item: _Medido) -> None:
        distancia, menos_s, chave = item.order_key
        # A INVERSÃO É POSIÇÃO A POSIÇÃO. `menos_s` já é `-s`, então invertê-lo
        # é `-menos_s`, que é `s` — ver o cabeçalho do módulo.
        entrada = (-distancia, -menos_s, _ChaveDescendente(chave), item)
        self._medidos += 1
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entrada)
            return
        heapq.heappushpop(self._heap, entrada)

    @property
    def measured(self) -> int:
        """Quantos candidatos foram MEDIDOS — e não quantos sobraram."""
        return self._medidos

    def drain(self) -> list[_Medido]:
        """Os melhores, na ordem canônica ASCENDENTE da tripla."""
        return sorted((item for _, _, _, item in self._heap), key=lambda m: m.order_key)


@final
@dataclass(frozen=True, slots=True)
class AvailabilityAwareHistoricalRetriever:
    """A varredura ciente de disponibilidade. Pura: não lê nada, não escreve nada.

    ELA RECEBE OS CANDIDATOS PRONTOS, como o oráculo do PR-06.1 — e pelo mesmo
    motivo: é o que torna a invariância de ordem, de lote e de piso
    demonstrável sobre listas em memória.
    """

    policy: CandidateUniversePolicy
    profile: ResolvedRetrievalProfile
    distance: AvailabilityAwareDistanceDefinition

    def __post_init__(self) -> None:
        if self.distance.profile.fingerprint != self.profile.fingerprint:
            raise ValidationError(
                "a definição de distância percorre outro perfil resolvido: os eixos "
                "somados não seriam os eixos declarados, e o número sairia plausível",
                context={
                    "distance_profile": self.distance.profile.fingerprint,
                    "profile": self.profile.fingerprint,
                },
            )

    # ------------------------------------------------------------ a leitura --

    @property
    def coverage_policy(self) -> object:
        return self.distance.coverage_policy

    def retrieve(
        self,
        *,
        query: HistoricalRetrievalQuery,
        snapshot: QuerySnapshot,
        candidates: Iterable[CandidateRow],
        reference_content_fingerprint: str,
    ) -> AvailabilityAwareRetrievalResult:
        """O top-K ciente de disponibilidade, sobre TODO o universo."""
        query.assert_snapshot_matches(snapshot)
        mascara_da_query = self.assert_query_admissible(snapshot)
        chaves = self.profile.feature_keys
        disponiveis = _contar(mascara_da_query)
        valores_da_query = tuple(snapshot.values.get(chave) for chave in chaves)

        universo = CandidateUniverseAccumulator()
        topo = _TopK(query.k)
        sem_cobertura = 0
        estruturais = 0
        for candidato in candidates:
            self._conferir_alinhamento(candidato, snapshot)
            universo.admit(candidato)
            motivo = self._estrutural(candidato, snapshot)
            if motivo is not None:
                universo.reject(motivo)
                estruturais += 1
                continue
            mascara = availability_mask(
                feature_keys=chaves,
                values=candidato.values,
                availabilities=candidato.availabilities,
                owner=f"o candidato {candidato.key.text}",
            )
            comum = shared_mask(mascara_da_query, mascara)
            cobertura = self.distance.assess(
                query_available=disponiveis,
                candidate_available=_contar(mascara),
                shared=_contar(comum),
            )
            if not cobertura.meets_shared_floor:
                universo.reject(IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE)
                sem_cobertura += 1
                continue
            valores = tuple(candidato.values.get(chave) for chave in chaves)
            topo.offer(
                _Medido(
                    breakdown=self.distance.evaluate(valores_da_query, valores, comum),
                    coverage=cobertura,
                    row=candidato,
                    candidate_mask=mascara,
                    shared=comum,
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
            descriptor=descritor,
            topo=topo,
            query_mask=mascara_da_query,
            query_values=valores_da_query,
            query_available=disponiveis,
            coverage_ineligible=sem_cobertura,
            structural_ineligible=estruturais,
        )

    # ------------------------------------------------------------ as guardas --

    def assert_query_admissible(self, snapshot: QuerySnapshot) -> tuple[bool, ...]:
        """A query pode perguntar? Devolve a máscara dela, ou levanta.

        ELA É PÚBLICA E É CHAMADA ANTES DA LEITURA DOS CANDIDATOS (§86). A
        recusa por cobertura da query não pode custar a varredura do universo:
        `retrieve` a chama de novo — defesa em profundidade, para quem usar o
        domínio direto —, e o caso de uso a chama ANTES de ir ao object store.

            sem isto, `candidates=await ...` como argumento de `retrieve`
            avalia a leitura ANTES de a recusa acontecer, e a query
            incomparável paga o preço inteiro do universo. Foi assim que o
            benchmark do PR-06.2 encontrou o defeito.
        """
        self._conferir_perfil(snapshot)
        chaves = self.profile.feature_keys
        mascara = availability_mask(
            feature_keys=chaves,
            values=snapshot.values,
            availabilities=snapshot.availabilities,
            owner=f"a query {snapshot.key.text}",
        )
        disponiveis = _contar(mascara)
        politica = self.distance.coverage_policy
        if not politica.admits_query(available=disponiveis, profile_axes=len(chaves)):
            raise QueryInsufficientCoverageError(
                key=snapshot.key,
                profile_fingerprint=self.profile.fingerprint,
                available_axes=disponiveis,
                axis_count=len(chaves),
                missing_axes=unselected(chaves, mascara),
                policy=politica,
            )
        return mascara

    def _conferir_perfil(self, snapshot: QuerySnapshot) -> None:
        """O perfil é grande bastante, e é da liga certa.

        O TAMANHO DO PERFIL É CONFERIDO ANTES DA QUERY, e a ordem importa: um
        perfil de três eixos recusa toda query daquela competição, e dizer
        «esta query não tem cobertura» esconderia que a causa é a liga inteira.
        """
        self.distance.coverage_policy.assert_profile_admissible(
            axis_count=self.profile.axis_count, competition=self.profile.competition
        )
        if snapshot.competition != self.profile.competition:
            raise ValidationError(
                f"a query é de {snapshot.competition} e o perfil foi resolvido para "
                f"{self.profile.competition}: os eixos e as escalas são de outra liga",
                context={
                    "profile": self.profile.competition,
                    "query": snapshot.competition,
                },
            )

    def _conferir_alinhamento(self, candidate: CandidateRow, snapshot: QuerySnapshot) -> None:
        """A mesma defesa em profundidade do PR-06.1, e pelo mesmo motivo."""
        if candidate.competition != snapshot.competition:
            raise ValidationError(
                f"candidato de {candidate.competition} para uma query de "
                f"{snapshot.competition}: a escala é ajustada por competição, e "
                "cruzá-las compara números normalizados por medianas diferentes",
                context={"candidate": candidate.key.text},
            )
        if not candidate.position.aligns_with(snapshot.position):
            raise ValidationError(
                f"candidato em {candidate.position.text} para uma query em "
                f"{snapshot.position.text}: sob "
                f"{self.policy.time_alignment.value} o instante é EXATO",
                context={
                    "candidate": candidate.position.text,
                    "query": snapshot.position.text,
                },
            )

    def _estrutural(
        self, candidate: CandidateRow, snapshot: QuerySnapshot
    ) -> IneligibilityReason | None:
        """As recusas que NÃO são ausência de dado — ou `None`.

        ELAS SÃO PERGUNTADAS ANTES DA COBERTURA. Um candidato da mesma partida
        contado como «sem cobertura» inflaria o número que este PR existe para
        medir com um defeito estrutural.
        """
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
        descriptor: CandidateUniverseDescriptor,
        topo: _TopK,
        query_mask: tuple[bool, ...],
        query_values: tuple[float | None, ...],
        query_available: int,
        coverage_ineligible: int,
        structural_ineligible: int,
    ) -> AvailabilityAwareRetrievalResult:
        vizinhos = tuple(
            AvailabilityAwareNeighbor(
                rank=posicao,
                key=item.row.key,
                match_id=item.row.match_id,
                competition=item.row.competition,
                season=item.row.season,
                position=item.row.position,
                row_digest=item.row.row_digest,
                dissimilarity=item.breakdown.value,
                evidence=build_evidence(
                    feature_keys=self.profile.feature_keys,
                    query_key=snapshot.key,
                    query_row_digest=snapshot.row_digest,
                    query_values=query_values,
                    query_mask=query_mask,
                    candidate_key=item.row.key,
                    candidate_row_digest=item.row.row_digest,
                    candidate_values=tuple(
                        item.row.values.get(chave) for chave in self.profile.feature_keys
                    ),
                    candidate_mask=item.candidate_mask,
                    shared=item.shared,
                    coverage=item.coverage,
                    breakdown=item.breakdown,
                    resolved_profile_fingerprint=self.profile.fingerprint,
                    distance_definition_fingerprint=self.distance.fingerprint,
                    coverage_policy_fingerprint=self.distance.coverage_policy.fingerprint,
                ),
            )
            for posicao, item in enumerate(topo.drain(), start=1)
        )
        return AvailabilityAwareRetrievalResult(
            query_key=snapshot.key,
            query_row_digest=snapshot.row_digest,
            competition=snapshot.competition,
            candidate_policy_fingerprint=self.policy.fingerprint,
            candidate_universe_fingerprint=descriptor.fingerprint,
            retrieval_profile_fingerprint=self.profile.base.fingerprint,
            resolved_profile_fingerprint=self.profile.fingerprint,
            coverage_policy_fingerprint=self.distance.coverage_policy.fingerprint,
            distance_definition_fingerprint=self.distance.fingerprint,
            axis_count=self.profile.axis_count,
            query_available_count=query_available,
            requested_k=query.k,
            universe_count=descriptor.candidate_count,
            coverage_eligible_count=topo.measured,
            coverage_ineligible_count=coverage_ineligible,
            structural_ineligible_count=structural_ineligible,
            neighbors=vizinhos,
            ineligible=dict(descriptor.ineligible),
            exhaustive=True,
        )
