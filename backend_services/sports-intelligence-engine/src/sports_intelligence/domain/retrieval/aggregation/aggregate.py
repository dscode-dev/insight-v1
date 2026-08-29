"""O vizinho ponderado e o agregado — genéricos para estado e trajetória.

O QUE ESTE MÓDULO NÃO FAZ, e é o que o define: ele não recalcula distância, não
reordena vizinhos, não lê nada, e não interpreta nada. Ele recebe um top-K exato
já produzido, atribui massa relativa por distância, e resume.

    entra   vizinhos EXATOS, com dissimilaridade e evidência
    sai     as mesmas identidades, com massa relativa e concentração

A ORDEM DE RECUPERAÇÃO É PRESERVADA. O top-K já tem desempate determinístico
decidido pelo retrieval; reordenar aqui por peso produziria uma segunda ordem
com autoridade ambígua. Os pesos são um ATRIBUTO dos vizinhos, e não um novo
critério de ordenação — quando a concentração precisa ser lida em ordem de
massa, isso acontece dentro de `top_mass`, e não no resultado.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.aggregation.kernel import (
    assert_distances,
    effective_sample_size,
    normalized_weights,
    top_mass,
    uniform_weights,
    weighted_mean,
)
from sports_intelligence.domain.retrieval.aggregation.policy import (
    DistanceWeightingPolicy,
    RetrievalKind,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

AGGREGATION_FINGERPRINT_ALGORITHM: Final[str] = "neighbor-aggregation-sha256-v1"


@final
class AggregationStatus(StrEnum):
    """O estado do agregado. Dois, e o segundo não é um zero.

    `NO_NEIGHBORS` EXISTE PARA NÃO MENTIR COM NÚMEROS. Um agregado vazio com
    `N_eff = 0` e soma de pesos `0` pareceria uma medição — «concentração
    mínima», «nenhuma massa» — quando o que houve foi ausência de vizinhos. O
    estado é dito, e os campos numéricos ficam `None`.
    """

    AGGREGATED = "AGGREGATED"
    NO_NEIGHBORS = "NO_NEIGHBORS"


@final
@dataclass(frozen=True, slots=True)
class WeightedNeighbor:
    """Um vizinho com a massa que o núcleo lhe atribuiu.

    ELE NÃO CARREGA O PAYLOAD INTEIRO. Identidade, posição no top-K,
    dissimilaridade exata e a impressão da evidência bastam para auditar a
    massa; copiar o resto multiplicaria memória por `K` sem acrescentar nada
    que a impressão já não amarre.
    """

    #: A identidade semântica do vizinho, como o retrieval a nomeou.
    identity: str
    #: A posição no top-K EXATO. Preservada, e nunca recalculada.
    retrieval_rank: int
    #: A dissimilaridade EXATA. A única entrada permitida do núcleo.
    dissimilarity: float
    #: A massa relativa. NÃO é probabilidade.
    normalized_weight: float
    #: A impressão da evidência do retrieval — a ponte para o suporte.
    evidence_fingerprint: str

    def __post_init__(self) -> None:
        if self.retrieval_rank < 1:
            raise ValidationError(f"posição {self.retrieval_rank} no top-K")
        if not (0.0 <= self.normalized_weight <= 1.0):
            raise ValidationError(
                f"massa relativa {self.normalized_weight!r} fora de [0,1]: ela é uma "
                "fração de uma soma que vale um"
            )

    def as_canonical(self) -> dict[str, object]:
        return {
            "dissimilarity": repr(float(self.dissimilarity)),
            "evidence_fingerprint": self.evidence_fingerprint,
            "identity": self.identity,
            "retrieval_rank": self.retrieval_rank,
        }

    @property
    def fingerprint(self) -> str:
        """A identidade semântica DESTE vizinho dentro do top-K (§44).

        O PESO NÃO ENTRA, pelo mesmo motivo que não entra na impressão do
        agregado: ele é derivado da distância, da política e do CONJUNTO. Dois
        vizinhos idênticos em conjuntos diferentes têm massas diferentes por
        renormalização, e amarrar o peso aqui faria a identidade do vizinho
        mudar por causa dos vizinhos ao lado dele.
        """
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()


@final
@dataclass(frozen=True, slots=True)
class NeighborAggregation:
    """O top-K exato, com massa relativa e concentração. Sem interpretação.

    A IMPRESSÃO COBRE ENTRADA E POLÍTICA, e não a saída. Vizinhos, distâncias e
    política determinam os pesos por completo; incluir os pesos na impressão
    seria hashear duas vezes a mesma informação e esconder a dependência.
    """

    query_identity: str
    kind: RetrievalKind
    policy: DistanceWeightingPolicy
    requested_k: int
    weighted_neighbors: tuple[WeightedNeighbor, ...] = ()
    status: AggregationStatus = AggregationStatus.AGGREGATED
    #: A impressão do resultado de recuperação que originou este agregado.
    retrieval_fingerprint: str = ""
    #: O resumo da evidência — descritivo, e NUNCA multiplicado no peso.
    evidence_summary: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.requested_k < 1:
            raise ValidationError(f"K = {self.requested_k}")
        identidades = [v.identity for v in self.weighted_neighbors]
        if len(set(identidades)) != len(identidades):
            raise ValidationError(
                "vizinho repetido no agregado: a mesma partida receberia massa duas "
                "vezes, e a soma dos pesos deixaria de descrever um conjunto"
            )
        posicoes = [v.retrieval_rank for v in self.weighted_neighbors]
        if posicoes != sorted(posicoes):
            raise ValidationError(
                "o agregado não está na ordem do top-K: a ordem de recuperação é "
                "determinística e reordená-la aqui criaria uma segunda autoridade"
            )
        if not self.weighted_neighbors and self.status is AggregationStatus.AGGREGATED:
            raise ValidationError(
                "agregado sem vizinhos declarado AGGREGATED: a ausência tem estado "
                "próprio (`NO_NEIGHBORS`) justamente para não virar um zero"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def neighbor_count(self) -> int:
        """`k`. SEPARADO de `N_eff` — são grandezas diferentes (§32)."""
        return len(self.weighted_neighbors)

    @property
    def weights(self) -> tuple[float, ...]:
        return tuple(v.normalized_weight for v in self.weighted_neighbors)

    @property
    def dissimilarities(self) -> tuple[float, ...]:
        return tuple(v.dissimilarity for v in self.weighted_neighbors)

    @property
    def effective_sample_size(self) -> float | None:
        """A CONCENTRAÇÃO. `None` quando não há vizinhos, e nunca zero."""
        return effective_sample_size(self.weights)

    @property
    def weighted_mean_dissimilarity(self) -> float | None:
        return weighted_mean(self.dissimilarities, self.weights)

    @property
    def minimum_dissimilarity(self) -> float | None:
        return min(self.dissimilarities) if self.weighted_neighbors else None

    @property
    def maximum_dissimilarity(self) -> float | None:
        return max(self.dissimilarities) if self.weighted_neighbors else None

    @property
    def max_neighbor_weight(self) -> float | None:
        return max(self.weights) if self.weighted_neighbors else None

    @property
    def top3_weight_mass(self) -> float | None:
        return top_mass(self.weights, how_many=3)

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """Entrada e política. Os pesos são DERIVADOS, e não entram (§42)."""
        return {
            "algorithm": AGGREGATION_FINGERPRINT_ALGORITHM,
            "kind": self.kind.value,
            "neighbors": [v.as_canonical() for v in self.weighted_neighbors],
            "policy_fingerprint": self.policy.fingerprint,
            "query_identity": self.query_identity,
            "requested_k": self.requested_k,
            "retrieval_fingerprint": self.retrieval_fingerprint,
            "status": self.status.value,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "effective_sample_size": self.effective_sample_size,
            "evidence_summary": dict(self.evidence_summary),
            "max_neighbor_weight": self.max_neighbor_weight,
            "maximum_dissimilarity": self.maximum_dissimilarity,
            "minimum_dissimilarity": self.minimum_dissimilarity,
            "neighbor_count": self.neighbor_count,
            "requested_k": self.requested_k,
            "status": self.status.value,
            "top3_weight_mass": self.top3_weight_mass,
            "weighted_mean_dissimilarity": self.weighted_mean_dissimilarity,
        }

    def __str__(self) -> str:
        if self.status is AggregationStatus.NO_NEIGHBORS:
            return f"{self.query_identity}: NO_NEIGHBORS"
        efetivo = self.effective_sample_size
        concentracao = "-" if efetivo is None else f"{efetivo:.2f}"
        return f"{self.query_identity}: {self.neighbor_count} vizinhos, N_eff={concentracao}"


def aggregate(
    *,
    query_identity: str,
    kind: RetrievalKind,
    policy: DistanceWeightingPolicy,
    requested_k: int,
    neighbors: Sequence[tuple[str, int, float, str]],
    retrieval_fingerprint: str = "",
    evidence_summary: Mapping[str, object] | None = None,
) -> NeighborAggregation:
    """Monta o agregado a partir de `(identidade, posição, distância, evidência)`.

    A TUPLA É MÍNIMA DE PROPÓSITO. Ela é tudo que a ponderação precisa, e
    aceitar o objeto de vizinho inteiro faria o núcleo depender do contrato de
    estado OU do de trajetória — e então haveria dois núcleos.

    A POLÍTICA PRECISA CASAR COM O TIPO. Ponderar vizinhos de trajetória com a
    política de estado produziria massas plausíveis sobre outra grandeza.
    """
    if policy.kind is not kind:
        raise ValidationError(
            f"política de {policy.kind.value} aplicada a vizinhos de {kind.value}: "
            "as duas distâncias vivem em escalas diferentes, e a massa sairia "
            "plausível medindo outra coisa",
            context={"policy": policy.identity},
        )
    if not neighbors:
        return NeighborAggregation(
            query_identity=query_identity,
            kind=kind,
            policy=policy,
            requested_k=requested_k,
            status=AggregationStatus.NO_NEIGHBORS,
            retrieval_fingerprint=retrieval_fingerprint,
            evidence_summary=dict(evidence_summary or {}),
        )

    distancias = [d for _, _, d, _ in neighbors]
    assert_distances(distancias)
    pesos = (
        uniform_weights(len(distancias))
        if policy.is_uniform
        else normalized_weights(distancias, lam=policy.lam)
    )
    return NeighborAggregation(
        query_identity=query_identity,
        kind=kind,
        policy=policy,
        requested_k=requested_k,
        weighted_neighbors=tuple(
            WeightedNeighbor(
                identity=identidade,
                retrieval_rank=posicao,
                dissimilarity=distancia,
                normalized_weight=peso,
                evidence_fingerprint=impressao,
            )
            for (identidade, posicao, distancia, impressao), peso in zip(
                neighbors, pesos, strict=True
            )
        ),
        retrieval_fingerprint=retrieval_fingerprint,
        evidence_summary=dict(evidence_summary or {}),
    )
