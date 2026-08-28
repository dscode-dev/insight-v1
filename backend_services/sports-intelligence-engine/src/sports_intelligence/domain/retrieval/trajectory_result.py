"""O vizinho e o resultado de trajetória — tipos NOVOS, ao lado dos outros dois.

TRÊS TIPOS DE VIZINHO CONVIVEM, e cada um mede uma pergunta diferente:

    HistoricalNeighbor              d²   nível, caso completo        PR-06.1
    AvailabilityAwareNeighbor       D    nível, cobertura            PR-06.2
    TrajectoryHistoricalNeighbor    D_T  MOVIMENTO, cobertura        PR-06.3

E OS TRÊS NÚMEROS NÃO SE COMPARAM ENTRE SI. `D = 0,2` e `D_T = 0,2` não são a
mesma grandeza: o primeiro é média de diferença de nível sobre `m` eixos, o
segundo é média de diferença de MOVIMENTO sobre `n = |H| · m` células. Tipos
separados são o que impede alguém de os somar por engano — e somá-los é
exatamente o que o §4 proíbe.

    NÃO EXISTE `D_total` NESTE PACOTE, e a ausência é a decisão. Combinar os
    dois exige escolher `alfa` e `beta`, e não há rótulo de verdade com que
    calibrá-los antes do PR-06.5.

A ORDEM É UMA QUÁDRUPLA, e cada critério entra por um motivo:

    1. dissimilaridade         ASC    quão parecido é o movimento
    2. células compartilhadas  DESC   sobre quanta evidência
    3. horizontes compartilhados DESC   distribuída em quantas escalas de tempo
    4. chave canônica          ASC    a reprodutibilidade

**O TERCEIRO CRITÉRIO É NOVO NESTE PR** (§122). Com `D_T` e contagem de células
iguais, a evidência espalhada em três horizontes descreve a forma do movimento
melhor que a mesma quantidade concentrada em dois: doze células em `1m` e `3m`
dizem o que aconteceu em três minutos; oito em `1m`, `3m` e `5m` dizem o que
aconteceu em cinco.

**E A COBERTURA CONTINUA NÃO LIDERANDO** (§123). Ela já está dentro do número
pela penalidade; usá-la como primeiro critério a contaria duas vezes, e um
candidato com movimento completamente diferente ganharia de um quase idêntico
por ter mais células.
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
from sports_intelligence.domain.retrieval.timepoint import GridTimePoint
from sports_intelligence.domain.retrieval.trajectory_evidence import (
    TrajectoryNeighborEvidence,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

TRAJECTORY_RESULT_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-retrieval-result-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class TrajectoryHistoricalNeighbor:
    """Um candidato no top-K de trajetória, com a prova temporal ao lado."""

    rank: int
    anchor_key: HistoricalFeatureSnapshotKey
    match_id: str
    competition: str
    season: str
    anchor_position: GridTimePoint
    anchor_row_digest: str
    trajectory_fingerprint: str
    #: `D_T`. Ela NÃO é `D` nem `d²` — ver o cabeçalho do módulo.
    trajectory_dissimilarity: float
    evidence: TrajectoryNeighborEvidence

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValidationError(f"vizinho com posição {self.rank}: o ranking começa em 1")
        if self.trajectory_dissimilarity < 0:
            raise ValidationError(
                f"dissimilaridade temporal negativa: {self.trajectory_dissimilarity!r}"
            )
        if self.evidence.candidate_anchor_key != self.anchor_key:
            raise ValidationError(
                f"o vizinho {self.anchor_key} carrega a evidência de "
                f"{self.evidence.candidate_anchor_key}"
            )
        if self.evidence.dissimilarity != self.trajectory_dissimilarity:
            raise ValidationError(
                f"o vizinho {self.anchor_key} declara "
                f"{self.trajectory_dissimilarity!r} e a evidência reconstrói "
                f"{self.evidence.dissimilarity!r}: o ranking usaria um número que a "
                "prova não sustenta"
            )
        if self.evidence.candidate_trajectory_fingerprint != self.trajectory_fingerprint:
            raise ValidationError(
                f"o vizinho {self.anchor_key} declara a trajetória "
                f"{self.trajectory_fingerprint[:12]} e a evidência a "
                f"{self.evidence.candidate_trajectory_fingerprint[:12]}"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def shared_cells(self) -> int:
        return self.evidence.shared_cell_count

    @property
    def shared_horizons(self) -> int:
        return self.evidence.shared_horizons

    @property
    def shared_coverage(self) -> float:
        return self.evidence.coverage.shared_coverage

    @property
    def penalty_share(self) -> float | None:
        return self.evidence.penalty_share

    @property
    def is_complete(self) -> bool:
        return self.evidence.coverage.is_complete

    @property
    def is_at_coverage_floor(self) -> bool:
        return self.evidence.coverage.is_at_shared_floor

    @property
    def canonical_key(self) -> str:
        return self.anchor_key.text

    @property
    def order_key(self) -> tuple[float, int, int, str]:
        """A quádrupla de ordenação, materializada.

        ELA É UMA PROPRIEDADE para que o heap, a conferência de ordem do
        resultado e os testes usem a MESMA definição — quatro lugares
        escrevendo a mesma quádrupla à mão é como um `<` vira `<=` num deles.
        """
        return (
            self.trajectory_dissimilarity,
            -self.shared_cells,
            -self.shared_horizons,
            self.canonical_key,
        )

    def as_canonical(self) -> dict[str, object]:
        return {
            "anchor_position": self.anchor_position.as_canonical(),
            "competition": self.competition,
            "evidence_fingerprint": self.evidence.fingerprint,
            "key": self.anchor_key.text,
            "match_id": self.match_id,
            "rank": self.rank,
            "row_digest": self.anchor_row_digest,
            "season": self.season,
            "shared_cells": self.shared_cells,
            "shared_horizons": self.shared_horizons,
            "trajectory_dissimilarity": distance_text(self.trajectory_dissimilarity),
            "trajectory_fingerprint": self.trajectory_fingerprint,
        }

    def __str__(self) -> str:
        return (
            f"#{self.rank} {self.anchor_key.text} "
            f"D_T={distance_text(self.trajectory_dissimilarity)} "
            f"s={self.shared_cells} h={self.shared_horizons}"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryRetrievalResult:
    """O top-K de trajetória, com a atrição temporal aberta em três."""

    query_anchor_key: HistoricalFeatureSnapshotKey
    query_anchor_row_digest: str
    query_trajectory_fingerprint: str
    query_anchor_position: GridTimePoint
    competition: str
    candidate_policy_fingerprint: str
    candidate_universe_fingerprint: str
    window_policy_fingerprint: str
    trajectory_profile_fingerprint: str
    coverage_policy_fingerprint: str
    distance_definition_fingerprint: str
    axis_count: int
    horizon_count: int
    cell_count: int
    query_usable_cells: int
    query_usable_horizons: int
    requested_k: int
    universe_count: int = 0
    trajectory_eligible_count: int = 0
    trajectory_ineligible_count: int = 0
    structural_ineligible_count: int = 0
    neighbors: tuple[TrajectoryHistoricalNeighbor, ...] = ()
    ineligible: Mapping[str, int] = field(default_factory=dict)
    exhaustive: bool = True

    def __post_init__(self) -> None:
        if self.cell_count != self.axis_count * self.horizon_count:
            raise ValidationError(
                f"{self.cell_count} células contra {self.axis_count} eixos x "
                f"{self.horizon_count} horizontes: o denominador declarado não é o "
                "produto que ele deveria ser"
            )
        if len(self.neighbors) > self.requested_k:
            raise ValidationError(
                f"{len(self.neighbors)} vizinhos para um pedido de {self.requested_k}"
            )
        soma = (
            self.trajectory_eligible_count
            + self.trajectory_ineligible_count
            + self.structural_ineligible_count
        )
        if soma != self.universe_count:
            raise ValidationError(
                f"{soma} candidatos classificados de um universo de "
                f"{self.universe_count}: todo candidato é elegível, recusado por "
                "evidência temporal ou recusado por estrutura — e nenhuma quarta "
                "coisa. Uma diferença aqui é candidato perdido pela varredura",
                context={
                    "eligible": self.trajectory_eligible_count,
                    "structural": self.structural_ineligible_count,
                    "trajectory_ineligible": self.trajectory_ineligible_count,
                    "universe": self.universe_count,
                },
            )
        if len(self.neighbors) > self.trajectory_eligible_count:
            raise ValidationError(
                f"{len(self.neighbors)} vizinhos de {self.trajectory_eligible_count} "
                "candidatos elegíveis: o top-K não pode devolver quem não foi medido"
            )
        esperados = tuple(range(1, len(self.neighbors) + 1))
        if tuple(v.rank for v in self.neighbors) != esperados:
            raise ValidationError("posições do ranking fora de sequência: elas são 1..N")
        anterior: tuple[float, int, int, str] | None = None
        for vizinho in self.neighbors:
            atual = vizinho.order_key
            if anterior is not None and atual < anterior:
                raise ValidationError(
                    f"vizinho {vizinho.anchor_key} fora da ordem canônica: o ranking é "
                    "por (D_T, células desc, horizontes desc, chave), e uma inversão "
                    "faria duas execuções produzirem rankings diferentes",
                    context={"key": vizinho.anchor_key.text},
                )
            anterior = atual
        for vizinho in self.neighbors:
            if (
                vizinho.evidence.trajectory_profile_fingerprint
                != self.trajectory_profile_fingerprint
            ):
                raise ValidationError(
                    f"o vizinho {vizinho.anchor_key} foi medido sob outro perfil de "
                    "trajetória: os números do ranking não estariam na mesma grandeza"
                )
            if vizinho.evidence.query_trajectory_fingerprint != self.query_trajectory_fingerprint:
                raise ValidationError(
                    f"o vizinho {vizinho.anchor_key} foi comparado contra outra trajetória de query"
                )
        if not self.exhaustive:
            raise ValidationError(
                "resultado do PR-06.3 declarado não exaustivo: a atrição temporal só é "
                "interpretável se TODO candidato do universo foi classificado"
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
        return (
            0.0 if not self.universe_count else self.trajectory_eligible_count / self.universe_count
        )

    @property
    def query_coverage(self) -> float:
        return self.query_usable_cells / self.cell_count

    @property
    def complete_neighbors(self) -> tuple[TrajectoryHistoricalNeighbor, ...]:
        return tuple(v for v in self.neighbors if v.is_complete)

    @property
    def floor_pressure(self) -> int:
        """Quantos vizinhos do top-K estão EXATAMENTE no piso temporal."""
        return sum(1 for v in self.neighbors if v.is_at_coverage_floor)

    @property
    def full_horizon_neighbors(self) -> int:
        """Quantos vizinhos usaram TODOS os horizontes."""
        return sum(1 for v in self.neighbors if v.shared_horizons == self.horizon_count)

    def top(self, k: int) -> tuple[TrajectoryHistoricalNeighbor, ...]:
        if k < 1:
            raise ValidationError(f"prefixo de tamanho {k}")
        return self.neighbors[:k]

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "cell_count": self.cell_count,
            "eligible_ratio": self.eligible_ratio,
            "floor_pressure": self.floor_pressure,
            "full_horizon_neighbors": self.full_horizon_neighbors,
            "horizon_count": self.horizon_count,
            "query_coverage": self.query_coverage,
            "query_usable_cells": self.query_usable_cells,
            "query_usable_horizons": self.query_usable_horizons,
            "requested_k": self.requested_k,
            "returned_k": self.returned_k,
            "structural_ineligible_count": self.structural_ineligible_count,
            "trajectory_eligible_count": self.trajectory_eligible_count,
            "trajectory_ineligible_count": self.trajectory_ineligible_count,
            "universe_count": self.universe_count,
            **{f"ineligible_{k}": v for k, v in sorted(self.ineligible.items())},
        }

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_RESULT_FINGERPRINT_ALGORITHM,
            "candidate_policy_fingerprint": self.candidate_policy_fingerprint,
            "candidate_universe_fingerprint": self.candidate_universe_fingerprint,
            "coverage_policy_fingerprint": self.coverage_policy_fingerprint,
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "neighbors": [
                {
                    "evidence_fingerprint": v.evidence.fingerprint,
                    "key": v.anchor_key.text,
                    "rank": v.rank,
                    "row_digest": v.anchor_row_digest,
                    "shared_cells": v.shared_cells,
                    "shared_horizons": v.shared_horizons,
                    "trajectory_dissimilarity": distance_text(v.trajectory_dissimilarity),
                }
                for v in self.neighbors
            ],
            "query_trajectory_fingerprint": self.query_trajectory_fingerprint,
            "requested_k": self.requested_k,
            "trajectory_profile_fingerprint": self.trajectory_profile_fingerprint,
            "window_policy_fingerprint": self.window_policy_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return (
            f"{self.query_anchor_key.text}@{self.query_anchor_position.text}: "
            f"{self.returned_k}/{self.requested_k} vizinhos de "
            f"{self.trajectory_eligible_count}/{self.universe_count} candidatos "
            f"[{self.fingerprint[:12]}]"
        )


def trajectory_result_summary(result: TrajectoryRetrievalResult) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    linhas = [
        f"query            {result.query_anchor_key.text}@{result.query_anchor_position.text}",
        f"competição       {result.competition}",
        f"espaço           {result.axis_count} eixos x {result.horizon_count} "
        f"horizontes = {result.cell_count} células",
        f"cobertura query  {result.query_usable_cells} ({result.query_coverage:.1%}) em "
        f"{result.query_usable_horizons} horizonte(s)",
        f"universo         {result.universe_count}",
        f"  elegíveis      {result.trajectory_eligible_count} ({result.eligible_ratio:.1%})",
        f"  sem trajetória {result.trajectory_ineligible_count}",
        f"  estruturais    {result.structural_ineligible_count}",
        f"K                {result.returned_k}/{result.requested_k}",
        f"no piso          {result.floor_pressure}",
        f"horizonte cheio  {result.full_horizon_neighbors}",
    ]
    linhas.extend(
        f"  inelegível {motivo}: {contagem}"
        for motivo, contagem in sorted(result.ineligible.items())
    )
    linhas.extend(str(vizinho) for vizinho in result.neighbors)
    linhas.append(f"impressão        {result.fingerprint[:16]}")
    return linhas
