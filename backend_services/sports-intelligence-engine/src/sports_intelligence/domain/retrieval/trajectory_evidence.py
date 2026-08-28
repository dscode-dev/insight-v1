"""A prova mecânica de um vizinho de trajetória — e a abertura por horizonte.

O CRITÉRIO É O DO PR-06.2, com uma exigência a mais. A partir da evidência tem
de ser possível reconstruir:

    D_T = (Observed_T + Missing_T) / n

E TAMBÉM DE ONDE O NÚMERO VEIO NO TEMPO. Dois vizinhos com o mesmo `D_T` podem
significar coisas opostas:

    todo o observado no horizonte de 1 min    eles divergiram AGORA
    todo o observado no horizonte de 5 min    eles vinham divergindo

O total é o mesmo; a leitura não é. Por isso a evidência carrega a contribuição
por horizonte — `shared_axes`, `observed`, `missing` e cobertura de cada um.

AS TRÊS MÁSCARAS SÃO SOBRE CÉLULAS `(horizonte, eixo)`, e não sobre eixos. Elas
têm `n = |H| · m` posições, na ordem canônica `horizonte` primeiro:

    perfil 3 eixos, horizontes 1/3/5    →  9 posições
    "111" "111" "000"                   →  o horizonte de 5 min está fora

ISTO CONTINUA NÃO SENDO EXPLICABILIDADE. Não há frase, não há «o jogo estava
subindo»; há máscaras, contagens e somas. O PR-06.7 vai construir a narrativa
SOBRE isto — o que é diferente de ser isto.

E ELA NÃO CARREGA DESFECHO. Nem vencedor, nem gol seguinte, nem — e este é
específico deste PR — a EVOLUÇÃO FUTURA. A trajetória olha para trás; carregar
`t+1` na evidência seria exatamente o vazamento que a janela existe para
impedir.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.features.dataset.rows import (
    HistoricalFeatureSnapshotKey,
)
from sports_intelligence.domain.retrieval.availability import mask_text
from sports_intelligence.domain.retrieval.distance import distance_text
from sports_intelligence.domain.retrieval.trajectory import TrajectoryRepresentation
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    TrajectoryCoverageAssessment,
)
from sports_intelligence.domain.retrieval.trajectory_distance import TrajectoryBreakdown
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

TRAJECTORY_EVIDENCE_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-evidence-sha256-v1"


@final
@dataclass(frozen=True, slots=True)
class TrajectoryDistanceContribution:
    """Quanto UMA célula `(horizonte, eixo)` contribuiu, e de quais movimentos.

    ELA É MECÂNICA. Não diz que o eixo «importa»; diz que a query se moveu
    `+0,8` naquele eixo nos últimos três minutos, o candidato se moveu `-0,4`,
    e que isso somou `1,44`.
    """

    horizon_minutes: int
    feature_key: str
    query_displacement: float
    candidate_displacement: float
    squared_contribution: float

    def __post_init__(self) -> None:
        if self.squared_contribution < 0:
            raise ValidationError(
                f"contribuição negativa em {self.horizon_minutes}m/{self.feature_key}: "
                f"{self.squared_contribution!r}"
            )

    @property
    def label(self) -> str:
        return f"{self.horizon_minutes}m/{self.feature_key}"

    @property
    def delta(self) -> float:
        return self.query_displacement - self.candidate_displacement

    @property
    def is_reversal(self) -> bool:
        """Se os dois se moveram em direções OPOSTAS naquela célula.

        ELA EXISTE PARA SER LIDA no relatório: a reversão é o fenômeno que este
        PR existe para separar, e uma contagem dela diz quanto do afastamento
        veio de direção contrária em vez de magnitude diferente.
        """
        return self.query_displacement * self.candidate_displacement < 0

    def as_canonical(self) -> dict[str, object]:
        return {
            "candidate_displacement": distance_text(self.candidate_displacement),
            "feature_key": self.feature_key,
            "horizon_minutes": self.horizon_minutes,
            "query_displacement": distance_text(self.query_displacement),
            "squared_contribution": distance_text(self.squared_contribution),
        }

    def __str__(self) -> str:
        return (
            f"{self.label}: {distance_text(self.query_displacement)} vs "
            f"{distance_text(self.candidate_displacement)} -> "
            f"{distance_text(self.squared_contribution)}"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryNeighborEvidence:
    """Tudo que sustenta a posição de um vizinho de trajetória."""

    candidate_anchor_key: HistoricalFeatureSnapshotKey
    candidate_trajectory_fingerprint: str
    query_anchor_key: HistoricalFeatureSnapshotKey
    query_trajectory_fingerprint: str
    window_policy_fingerprint: str
    trajectory_profile_fingerprint: str
    coverage_policy_fingerprint: str
    distance_definition_fingerprint: str
    #: As três máscaras, sobre `n` células em ordem `(horizonte, eixo)`.
    query_cell_mask: str
    candidate_cell_mask: str
    shared_cell_mask: str
    coverage: TrajectoryCoverageAssessment
    breakdown: TrajectoryBreakdown
    shared_cells: tuple[str, ...] = ()
    unshared_cells: tuple[str, ...] = ()
    #: As contribuições por célula compartilhada. OPCIONAIS no contrato e
    #: presentes na prática só para quem sobreviveu ao top-K (§113).
    contributions: tuple[TrajectoryDistanceContribution, ...] = ()

    def __post_init__(self) -> None:
        tamanhos = {
            len(self.query_cell_mask),
            len(self.candidate_cell_mask),
            len(self.shared_cell_mask),
        }
        if tamanhos != {self.coverage.cell_count}:
            raise ValidationError(
                f"máscaras de tamanhos {sorted(tamanhos)} contra um espaço de "
                f"{self.coverage.cell_count} células: elas são posicionais sobre "
                "(horizonte, eixo), e um tamanho diferente descreve outro espaço"
            )
        if self.breakdown.cell_count != self.coverage.cell_count:
            raise ValidationError("a conta e a cobertura discordam sobre o tamanho do espaço")
        if self.breakdown.shared_cells != self.coverage.shared_cells:
            raise ValidationError(
                f"a conta usou {self.breakdown.shared_cells} células e a cobertura "
                f"declara {self.coverage.shared_cells}: a penalidade e o piso estariam "
                "falando de máscaras diferentes"
            )
        if len(self.shared_cells) != self.coverage.shared_cells:
            raise ValidationError(
                f"{len(self.shared_cells)} células compartilhadas nomeadas e "
                f"{self.coverage.shared_cells} contadas"
            )
        if self.contributions and len(self.contributions) != self.coverage.shared_cells:
            raise ValidationError(
                f"{len(self.contributions)} contribuições para "
                f"{self.coverage.shared_cells} células compartilhadas: uma evidência "
                "com contribuições parciais não reconstrói a soma"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def dissimilarity(self) -> float:
        return self.breakdown.value

    @property
    def observed_sum(self) -> float:
        return self.breakdown.observed_sum

    @property
    def missing_penalty_sum(self) -> float:
        return self.breakdown.missing_penalty_sum

    @property
    def penalty_share(self) -> float | None:
        return self.breakdown.penalty_share

    @property
    def shared_cell_count(self) -> int:
        return self.coverage.shared_cells

    @property
    def shared_horizons(self) -> int:
        return self.coverage.shared_horizons

    @property
    def effective_shared_cell_floor(self) -> int:
        """QUANTAS células este vizinho precisava ter — `max(8, ceil(3n/5))`.

        ELA EXISTE PARA QUE A EVIDÊNCIA SEJA DIZÍVEL. «Vinte e sete de
        quarenta e cinco» é uma contagem; «vinte e sete, e o piso era vinte e
        sete» é a razão pela qual ele está aqui, e a mesma frase serve para
        explicar quem ficou de fora.
        """
        return self.coverage.effective_shared_cell_floor

    @property
    def effective_horizon_axis_floor(self) -> int:
        """`E_h = max(4, ceil(3m/5))` — o piso de um horizonte evidencial."""
        return self.coverage.effective_horizon_axis_floor

    @property
    def margin_over_shared_cell_floor(self) -> int:
        """Quantas células ACIMA do piso efetivo. Zero é a fronteira exata."""
        return self.shared_cell_count - self.effective_shared_cell_floor

    @property
    def reversals(self) -> int:
        """Em quantas células os dois se moveram em direções opostas."""
        return sum(1 for c in self.contributions if c.is_reversal)

    @property
    def is_reconstructible(self) -> bool:
        """Se as contribuições reconstroem a soma observada (§242).

        `fsum` CONTRA `fsum`, e não com tolerância — as duas somas percorrem os
        mesmos termos na mesma ordem, e uma tolerância aqui esconderia
        justamente o defeito que ela procura.
        """
        if not self.contributions:
            return False
        return math.fsum(c.squared_contribution for c in self.contributions) == self.observed_sum

    def horizon_contributions(self) -> Sequence[Mapping[str, object]]:
        """A abertura por horizonte, pronta para o relatório (§111)."""
        return [
            {
                "coverage": c.coverage,
                "horizon_minutes": c.horizon_minutes,
                "missing_penalty": c.missing_penalty,
                "observed": c.observed,
                "share_of_observed": self.breakdown.horizon_share(c.horizon_minutes),
                "shared_axes": c.shared_axes,
            }
            for c in self.breakdown.horizons
        ]

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """A identidade — quem, sob que régua, com que conta e em que horizontes.

        AS DUAS TRAJETÓRIAS ENTRAM POR IMPRESSÃO, e é isso que amarra a
        evidência às linhas de origem: a impressão da trajetória já cobre a
        âncora, os slots e os digestos de cada linha de lookback.

        AS CONTRIBUIÇÕES FICAM DE FORA — derivadas exatas dos deslocamentos, e
        os deslocamentos já entram pelas impressões das duas representações.
        """
        return {
            "algorithm": TRAJECTORY_EVIDENCE_FINGERPRINT_ALGORITHM,
            "candidate_anchor_key": self.candidate_anchor_key.text,
            "candidate_cell_mask": self.candidate_cell_mask,
            "candidate_trajectory_fingerprint": self.candidate_trajectory_fingerprint,
            "coverage": self.coverage.as_canonical(),
            "coverage_policy_fingerprint": self.coverage_policy_fingerprint,
            "dissimilarity": distance_text(self.dissimilarity),
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "horizons": [c.as_canonical() for c in self.breakdown.horizons],
            "missing_penalty_sum": distance_text(self.missing_penalty_sum),
            "observed_sum": distance_text(self.observed_sum),
            "query_anchor_key": self.query_anchor_key.text,
            "query_cell_mask": self.query_cell_mask,
            "query_trajectory_fingerprint": self.query_trajectory_fingerprint,
            "shared_cell_mask": self.shared_cell_mask,
            "trajectory_profile_fingerprint": self.trajectory_profile_fingerprint,
            "window_policy_fingerprint": self.window_policy_fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "dissimilarity": self.dissimilarity,
            "missing_penalty_sum": self.missing_penalty_sum,
            "observed_sum": self.observed_sum,
            "penalty_share": self.penalty_share,
            "effective_horizon_axis_floor": self.effective_horizon_axis_floor,
            "effective_shared_cell_floor": self.effective_shared_cell_floor,
            "margin_over_shared_cell_floor": self.margin_over_shared_cell_floor,
            "reversals": self.reversals,
            "shared_cells": self.shared_cell_count,
            "shared_coverage": self.coverage.shared_coverage,
            "shared_horizons": self.shared_horizons,
        }

    def __str__(self) -> str:
        return (
            f"{self.candidate_anchor_key.text}: D_T="
            f"{distance_text(self.dissimilarity)} s={self.shared_cell_count}"
            f"/{self.coverage.cell_count} (piso {self.effective_shared_cell_floor}) "
            f"em {self.shared_horizons} horizonte(s)"
        )


def build_trajectory_evidence(
    *,
    query: TrajectoryRepresentation,
    candidate: TrajectoryRepresentation,
    coverage: TrajectoryCoverageAssessment,
    breakdown: TrajectoryBreakdown,
    window_policy_fingerprint: str,
    trajectory_profile_fingerprint: str,
    coverage_policy_fingerprint: str,
    distance_definition_fingerprint: str,
    with_contributions: bool = True,
) -> TrajectoryNeighborEvidence:
    """Monta a evidência a partir das duas representações.

    `with_contributions` EXISTE PELA MEMÓRIA (§113). Montar as contribuições de
    todo candidato faria a alocação seguir o universo vezes `n`; montá-las só
    para quem entrou no top-K a mantém em `O(K · n)`.
    """
    compartilhada = tuple(q and c for q, c in zip(query.mask, candidate.mask, strict=True))
    rotulos = tuple(f"{h}m/{chave}" for h in query.horizons for chave in query.feature_keys)
    contribuicoes: list[TrajectoryDistanceContribution] = []
    compartilhadas: list[str] = []
    ausentes: list[str] = []
    eixos = len(query.feature_keys)
    for posicao, rotulo in enumerate(rotulos):
        if not compartilhada[posicao]:
            ausentes.append(rotulo)
            continue
        compartilhadas.append(rotulo)
        if not with_contributions:
            continue
        dq = query.displacements[posicao]
        dc = candidate.displacements[posicao]
        if dq is None or dc is None:  # pragma: no cover — a máscara garantiu
            raise ValidationError(f"célula {rotulo} compartilhada e sem deslocamento")
        delta = dq - dc
        contribuicoes.append(
            TrajectoryDistanceContribution(
                horizon_minutes=query.horizons[posicao // eixos],
                feature_key=query.feature_keys[posicao % eixos],
                query_displacement=dq,
                candidate_displacement=dc,
                squared_contribution=delta * delta,
            )
        )
    return TrajectoryNeighborEvidence(
        candidate_anchor_key=candidate.trajectory.anchor_key,
        candidate_trajectory_fingerprint=candidate.fingerprint,
        query_anchor_key=query.trajectory.anchor_key,
        query_trajectory_fingerprint=query.fingerprint,
        window_policy_fingerprint=window_policy_fingerprint,
        trajectory_profile_fingerprint=trajectory_profile_fingerprint,
        coverage_policy_fingerprint=coverage_policy_fingerprint,
        distance_definition_fingerprint=distance_definition_fingerprint,
        query_cell_mask=query.mask_text,
        candidate_cell_mask=candidate.mask_text,
        shared_cell_mask=mask_text(compartilhada),
        coverage=coverage,
        breakdown=breakdown,
        shared_cells=tuple(compartilhadas),
        unshared_cells=tuple(ausentes),
        contributions=tuple(contribuicoes),
    )


def trajectory_evidence_summary(
    evidence: TrajectoryNeighborEvidence,
) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    parcela = evidence.penalty_share
    linhas = [
        f"vizinho          {evidence.candidate_anchor_key.text}",
        f"dissimilaridade  {distance_text(evidence.dissimilarity)}",
        f"  observado      {distance_text(evidence.observed_sum)}",
        f"  incerteza      {distance_text(evidence.missing_penalty_sum)}",
        "  fracao incerta " + ("-" if parcela is None else format(parcela, ".1%")),
        f"células          {evidence.shared_cell_count}"
        f"/{evidence.coverage.cell_count}"
        f" ({evidence.coverage.shared_coverage:.1%})",
        f"horizontes       {evidence.shared_horizons}",
        f"reversões        {evidence.reversals}",
    ]
    for contribuicao in evidence.breakdown.horizons:
        parcela_h = evidence.breakdown.horizon_share(contribuicao.horizon_minutes)
        sufixo = "" if parcela_h is None else f"  ({parcela_h:.0%} do observado)"
        linhas.append(f"  {contribuicao}{sufixo}")
    linhas.extend(
        [
            f"máscara query    {evidence.query_cell_mask}",
            f"máscara cand.    {evidence.candidate_cell_mask}",
            f"máscara comum    {evidence.shared_cell_mask}",
            f"impressão        {evidence.fingerprint[:16]}",
        ]
    )
    return linhas
