"""O vizinho e o resultado cientes de disponibilidade — tipos NOVOS, ao lado.

POR QUE TIPOS NOVOS, E NÃO CAMPOS A MAIS NO `HistoricalNeighbor` (§62). Um
`HistoricalNeighbor` com `evidence` opcional teria dois significados no mesmo
objeto — «medido sob caso completo» e «medido sob cobertura compartilhada» —, e
a diferença entre os dois estaria num campo que pode estar vazio. O dia em que
alguém comparasse dois números desses achando que são a mesma grandeza, nada
denunciaria.

    HistoricalNeighbor              d² sobre o perfil INTEIRO   PR-06.1
    AvailabilityAwareNeighbor       D sobre o perfil com piso   PR-06.2

E OS DOIS COEXISTEM DE PROPÓSITO (§73, §74). O oráculo de caso completo
continua executável: sem ele, «a política de ausência mudou o quê?» não teria
contra o que ser medido.

A ORDEM É UMA TRIPLA, E A ORDEM DELA É UMA DECISÃO (§67, §69):

    1. dissimilaridade   ASC
    2. eixos compartilhados  DESC
    3. chave canônica    ASC

**A COBERTURA DESEMPATA, E NÃO LIDERA.** Ordenar por cobertura primeiro faria
um candidato completamente diferente com 100 % de cobertura ganhar
necessariamente de um quase idêntico com 95 % — e cobertura viraria prioridade
absoluta em vez de evidência. Ela já está DENTRO do número, pela penalidade:
usá-la de novo como primeiro critério a contaria duas vezes.

**MAS ELA DESEMPATA ANTES DA CHAVE**, e isso não é arbitrário: quando dois
candidatos produzem exatamente o mesmo `D`, aquele que o produziu com mais
eixos observados o sustenta com mais evidência. A chave canônica entra por
último, e só existe para que o resultado seja reproduzível quando os dois
primeiros critérios empatam.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.retrieval.evidence import NeighborEvidence
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

AVAILABILITY_RESULT_FINGERPRINT_ALGORITHM: Final[str] = (
    "availability-aware-retrieval-result-sha256-v1"
)


@final
@dataclass(frozen=True, slots=True)
class AvailabilityAwareNeighbor:
    """Um candidato no top-K, com a evidência que o sustenta ao lado.

    A EVIDÊNCIA NÃO É OPCIONAL AQUI. Um vizinho classificado por uma conta que
    inclui incerteza precisa carregar quanto dele era incerteza — senão o
    número tem duas leituras opostas e nenhuma forma de escolher entre elas.
    """

    rank: int
    key: HistoricalFeatureSnapshotKey
    match_id: str
    competition: str
    season: str
    position: GridTimePoint
    row_digest: str
    #: `D_AA`. Ela NÃO é `d²`: o denominador é o número de eixos do perfil, e a
    #: incerteza dos eixos ausentes está dentro dela. Comparar este número com
    #: um `squared_distance` do PR-06.1 compara grandezas diferentes — e a
    #: equivalência entre eles vale só no caso completo, onde `D = d²/m`.
    dissimilarity: float
    evidence: NeighborEvidence

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValidationError(f"vizinho com posição {self.rank}: o ranking começa em 1")
        if self.dissimilarity < 0:
            raise ValidationError(
                f"dissimilaridade negativa: {self.dissimilarity!r}. Ela é uma soma de "
                "quadrados com uma penalidade não negativa, e não pode ser negativa"
            )
        if self.evidence.candidate_key != self.key:
            raise ValidationError(
                f"o vizinho {self.key} carrega a evidência de "
                f"{self.evidence.candidate_key}: a prova seria de outro candidato",
                context={"neighbor": self.key.text},
            )
        if self.evidence.dissimilarity != self.dissimilarity:
            raise ValidationError(
                f"o vizinho {self.key} declara {self.dissimilarity!r} e a evidência "
                f"reconstrói {self.evidence.dissimilarity!r}: o ranking usaria um "
                "número que a prova não sustenta",
                context={"neighbor": self.key.text},
            )

    # ------------------------------------------------------------ leitura --

    @property
    def shared_count(self) -> int:
        return self.evidence.shared_count

    @property
    def shared_coverage(self) -> float:
        return self.evidence.coverage.shared_profile_coverage

    @property
    def penalty_share(self) -> float | None:
        return self.evidence.penalty_share

    @property
    def is_complete_case(self) -> bool:
        """Se este vizinho compartilhou o perfil inteiro com a query.

        ELE É O SUBCONJUNTO EM QUE A EQUIVALÊNCIA COM O PR-06.1 VALE (§41), e
        é por isso que ele é uma propriedade e não um cálculo espalhado pelos
        testes.
        """
        return self.evidence.coverage.is_complete_case

    @property
    def is_at_coverage_floor(self) -> bool:
        return self.evidence.coverage.is_at_shared_floor

    @property
    def canonical_key(self) -> str:
        return self.key.text

    @property
    def order_key(self) -> tuple[float, int, str]:
        """A tripla de ordenação, materializada.

        ELA EXISTE COMO PROPRIEDADE para que o heap, a conferência de ordem do
        resultado e os testes usem a MESMA definição. Três lugares escrevendo
        a mesma tripla à mão é como um `<` vira um `<=` num deles só.
        """
        return (self.dissimilarity, -self.shared_count, self.canonical_key)

    def as_canonical(self) -> dict[str, object]:
        return {
            "competition": self.competition,
            "dissimilarity": distance_text(self.dissimilarity),
            "evidence_fingerprint": self.evidence.fingerprint,
            "key": self.key.text,
            "match_id": self.match_id,
            "position": self.position.as_canonical(),
            "rank": self.rank,
            "row_digest": self.row_digest,
            "season": self.season,
            "shared_count": self.shared_count,
        }

    def __str__(self) -> str:
        return (
            f"#{self.rank} {self.key.text} D={distance_text(self.dissimilarity)} "
            f"s={self.shared_count}"
        )


@final
@dataclass(frozen=True, slots=True)
class AvailabilityAwareRetrievalResult:
    """O top-K ciente de disponibilidade, com a atrição aberta em três.

    A ATRIÇÃO É ABERTA EM TRÊS, E NÃO EM DUAS (§63). O PR-06.1 tinha «comparável
    ou não»; aqui a diferença entre «não alcançou o piso» e «não deveria estar
    no universo» é o insumo que separa a medição do defeito:

        coverage_eligible      recebeu distância
        coverage_ineligible    está no universo e não alcançou o piso. NORMAL,
                               e é o número que este PR existe para medir
        structural_ineligible  mesma partida, representação divergente. NÃO
                               deveria acontecer

    Somá-los faria uma queda de integridade se disfarçar de ausência de dado.
    """

    query_key: HistoricalFeatureSnapshotKey
    query_row_digest: str
    competition: str
    candidate_policy_fingerprint: str
    candidate_universe_fingerprint: str
    retrieval_profile_fingerprint: str
    resolved_profile_fingerprint: str
    coverage_policy_fingerprint: str
    distance_definition_fingerprint: str
    axis_count: int
    query_available_count: int
    requested_k: int
    universe_count: int = 0
    coverage_eligible_count: int = 0
    coverage_ineligible_count: int = 0
    structural_ineligible_count: int = 0
    neighbors: tuple[AvailabilityAwareNeighbor, ...] = ()
    ineligible: Mapping[str, int] = field(default_factory=dict)
    exhaustive: bool = True

    def __post_init__(self) -> None:
        if len(self.neighbors) > self.requested_k:
            raise ValidationError(
                f"{len(self.neighbors)} vizinhos para um pedido de {self.requested_k}"
            )
        soma = (
            self.coverage_eligible_count
            + self.coverage_ineligible_count
            + self.structural_ineligible_count
        )
        if soma != self.universe_count:
            raise ValidationError(
                f"{soma} candidatos classificados de um universo de "
                f"{self.universe_count}: todo candidato do universo é elegível, "
                "recusado por cobertura ou recusado por estrutura — e nenhuma quarta "
                "coisa. Uma diferença aqui é candidato perdido pela varredura",
                context={
                    "coverage_eligible": self.coverage_eligible_count,
                    "coverage_ineligible": self.coverage_ineligible_count,
                    "structural_ineligible": self.structural_ineligible_count,
                    "universe": self.universe_count,
                },
            )
        if len(self.neighbors) > self.coverage_eligible_count:
            raise ValidationError(
                f"{len(self.neighbors)} vizinhos de {self.coverage_eligible_count} "
                "candidatos elegíveis: o top-K não pode devolver quem não foi medido"
            )
        esperados = tuple(range(1, len(self.neighbors) + 1))
        if tuple(v.rank for v in self.neighbors) != esperados:
            raise ValidationError("posições do ranking fora de sequência: elas são 1..N")
        anterior: tuple[float, int, str] | None = None
        for vizinho in self.neighbors:
            atual = vizinho.order_key
            if anterior is not None and atual < anterior:
                raise ValidationError(
                    f"vizinho {vizinho.key} fora da ordem canônica: o ranking é por "
                    "(dissimilaridade, eixos compartilhados desc, chave), e uma "
                    "inversão faria duas execuções produzirem rankings diferentes "
                    "sobre os mesmos números",
                    context={"key": vizinho.key.text},
                )
            anterior = atual
        for vizinho in self.neighbors:
            if vizinho.evidence.resolved_profile_fingerprint != self.resolved_profile_fingerprint:
                raise ValidationError(
                    f"o vizinho {vizinho.key} foi medido sob outro perfil resolvido: "
                    "os números do ranking não estariam na mesma grandeza",
                    context={"key": vizinho.key.text},
                )
        if not self.exhaustive:
            raise ValidationError(
                "resultado do PR-06.2 declarado não exaustivo: a atrição por cobertura "
                "só é interpretável se TODO candidato do universo foi classificado"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def returned_k(self) -> int:
        return len(self.neighbors)

    @property
    def is_empty(self) -> bool:
        return not self.neighbors

    @property
    def eligible_ratio(self) -> float:
        """`elegíveis / universo`. Diagnóstico, e nunca insumo de pontuação."""
        return (
            0.0 if not self.universe_count else self.coverage_eligible_count / self.universe_count
        )

    @property
    def query_coverage(self) -> float:
        return self.query_available_count / self.axis_count

    @property
    def complete_case_neighbors(self) -> tuple[AvailabilityAwareNeighbor, ...]:
        """Os vizinhos que compartilharam o perfil inteiro.

        É SOBRE ELES QUE A EQUIVALÊNCIA COM O PR-06.1 É VERIFICADA (§42): a
        ordem relativa deste subconjunto tem de ser a mesma que o oráculo de
        caso completo produz sobre os mesmos candidatos.
        """
        return tuple(v for v in self.neighbors if v.is_complete_case)

    @property
    def floor_pressure(self) -> int:
        """Quantos vizinhos do top-K estão EXATAMENTE no piso (§156).

        SE A MAIORIA ESTIVER, O RANKING ESTÁ SENDO DOMINADO PELA FRONTEIRA — e
        isso é para reportar, não para corrigir automaticamente (§157).
        """
        return sum(1 for v in self.neighbors if v.is_at_coverage_floor)

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "coverage_eligible_count": self.coverage_eligible_count,
            "coverage_ineligible_count": self.coverage_ineligible_count,
            "eligible_ratio": self.eligible_ratio,
            "floor_pressure": self.floor_pressure,
            "query_available_count": self.query_available_count,
            "query_coverage": self.query_coverage,
            "requested_k": self.requested_k,
            "returned_k": self.returned_k,
            "structural_ineligible_count": self.structural_ineligible_count,
            "universe_count": self.universe_count,
            **{f"ineligible_{k}": v for k, v in sorted(self.ineligible.items())},
        }

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A pergunta e a resposta — com a evidência de cada vizinho por impressão.

        A IMPRESSÃO DA EVIDÊNCIA ENTRA (§72), e não só a distância. Dois
        rankings idênticos em ordem e em número podem ter chegado lá por
        máscaras diferentes — e essa diferença é exatamente o que este PR
        introduziu. Deixá-la de fora faria a impressão dizer «mesmo resultado»
        para duas coisas que não são a mesma.
        """
        return {
            "algorithm": AVAILABILITY_RESULT_FINGERPRINT_ALGORITHM,
            "candidate_policy_fingerprint": self.candidate_policy_fingerprint,
            "candidate_universe_fingerprint": self.candidate_universe_fingerprint,
            "coverage_policy_fingerprint": self.coverage_policy_fingerprint,
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "neighbors": [
                {
                    "dissimilarity": distance_text(v.dissimilarity),
                    "evidence_fingerprint": v.evidence.fingerprint,
                    "key": v.key.text,
                    "rank": v.rank,
                    "row_digest": v.row_digest,
                    "shared_count": v.shared_count,
                }
                for v in self.neighbors
            ],
            "query_row_digest": self.query_row_digest,
            "requested_k": self.requested_k,
            "resolved_profile_fingerprint": self.resolved_profile_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def top(self, k: int) -> tuple[AvailabilityAwareNeighbor, ...]:
        """O prefixo de tamanho `k` — para a propriedade do prefixo (§133)."""
        if k < 1:
            raise ValidationError(f"prefixo de tamanho {k}")
        return self.neighbors[:k]

    def __str__(self) -> str:
        return (
            f"{self.query_key.text}: {self.returned_k}/{self.requested_k} vizinhos de "
            f"{self.coverage_eligible_count}/{self.universe_count} candidatos "
            f"[{self.fingerprint[:12]}]"
        )


def availability_result_summary(
    result: AvailabilityAwareRetrievalResult,
) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"query           {result.query_key.text}",
        f"competição      {result.competition}",
        f"eixos           {result.axis_count}",
        f"cobertura query {result.query_available_count} ({result.query_coverage:.1%})",
        f"universo        {result.universe_count}",
        f"  elegíveis     {result.coverage_eligible_count} ({result.eligible_ratio:.1%})",
        f"  sem cobertura {result.coverage_ineligible_count}",
        f"  estruturais   {result.structural_ineligible_count}",
        f"K               {result.returned_k}/{result.requested_k}",
        f"no piso         {result.floor_pressure}",
    ]
    linhas.extend(
        f"  inelegível {motivo}: {contagem}"
        for motivo, contagem in sorted(result.ineligible.items())
    )
    linhas.extend(str(vizinho) for vizinho in result.neighbors)
    linhas.append(f"impressão       {result.fingerprint[:16]}")
    return linhas
