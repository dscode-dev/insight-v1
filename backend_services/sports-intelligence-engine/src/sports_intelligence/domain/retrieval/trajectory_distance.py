"""A dissimilaridade de trajetória — a mesma forma do PR-06.2, outra unidade.

                Σ_{(h,i)∈S_T} (Δ^q_{h,i} - Δ^c_{h,i})²  +  p·(n - s)
    D_T(q,c) = ────────────────────────────────────────────────────      p = 1
                                        n = |H| · m

ELA REUSA A FORMA DO PR-06.2 DE PROPÓSITO. Denominador fixo, penalidade
uniforme, pesos iguais — as três decisões já foram tomadas e justificadas no
ADR-0044, e mudá-las aqui faria a comparação entre estado e trajetória medir
duas coisas de uma vez.

**O QUE MUDA É A UNIDADE DA CÉLULA.** Lá a célula era um eixo; aqui é
`(horizonte, eixo)`. E o que a célula CONTÉM também muda:

    estado        (q_i - c_i)²          a diferença de NÍVEL
    trajetória    (Δ^q - Δ^c)²          a diferença de MOVIMENTO

**A PENALIDADE CONTINUA VALENDO `1`, E A UNIDADE CONTINUA FAZENDO SENTIDO.**
`Δ` é a diferença entre dois valores normalizados pelo IQR da competição, logo
`Δ` vive em unidades de IQR — as MESMAS do estado. É por isso que não dividimos
por `h`: `Δ/h` viveria em «IQR por minuto», e uma penalidade de `1` ali seria
um número sem relação com o do PR-06.2.

**A REVERSÃO CUSTA O DOBRO AO QUADRADO**, e isso é a semântica certa:

    Δ^q = +2   e   Δ^c = -2      →  (Δ^q - Δ^c)² = (2·Δ^q)² = 16

Dois jogos no mesmo estado atual, um subindo e outro descendo, ficam a
dezesseis unidades de distância numa célula em que dois jogos subindo juntos
ficam a zero. É esse contraste que o PR existe para produzir.

**AUSÊNCIA NÃO É MOVIMENTO ZERO** (§99, §102). Uma célula ausente custa `1`, e
não `0`. Preencher o extremo que falta com o valor da âncora produziria
`Δ = 0` — «este jogo não se moveu» — que é ESTABILIDADE INVENTADA, e é o
blocker mais perigoso deste PR: ela não falha, ela mente com aparência de calma.

**E NÃO HÁ SCORE COMBINADO** (§4, §258). Este módulo produz `D_T`. O `D_state`
é do PR-06.2. Somá-los exigiria decidir `alfa` e `beta`, e não há rótulo de verdade
com que calibrá-los antes do PR-06.5.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.availability_distance import (
    FIXED_PROFILE_DENOMINATOR_V1,
    MISSING_AXIS_PENALTY,
)
from sports_intelligence.domain.retrieval.distance import FLOAT_SEMANTICS_V1
from sports_intelligence.domain.retrieval.trajectory import (
    DISPLACEMENT_REPRESENTATION_V1,
    TrajectoryRepresentation,
)
from sports_intelligence.domain.retrieval.trajectory_coverage import (
    DEFAULT_TRAJECTORY_COVERAGE,
    HorizonCoverage,
    TrajectoryCoverageAssessment,
    TrajectoryCoveragePolicy,
)
from sports_intelligence.domain.retrieval.trajectory_profile import (
    ResolvedTrajectoryProfile,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

TRAJECTORY_DISTANCE_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-distance-sha256-v1"

#: A política de penalidade. Ela é a MESMA do PR-06.2 em valor e em unidade —
#: e o nome diz que a célula agora é `(horizonte, eixo)`.
MISSING_TRAJECTORY_CELL_PENALTY_SQUARED_IQR_V1: Final[str] = (
    "MISSING_TRAJECTORY_CELL_PENALTY_SQUARED_IQR_V1"
)

#: `p`. Uma unidade quadrática de incerteza em escala IQR de DESLOCAMENTO.
MISSING_CELL_PENALTY: Final[float] = MISSING_AXIS_PENALTY


@final
class TrajectoryDistanceMethod(StrEnum):
    """Como a dissimilaridade temporal é calculada. Catálogo FECHADO."""

    #: `(Σ_S (Δq-Δc)² + p·u) / n`, pesos iguais, denominador fixo.
    MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY = (
        "MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY_V1"
    )


@final
@dataclass(frozen=True, slots=True)
class HorizonContribution:
    """Quanto UM horizonte contribuiu — mecânico, por horizonte (§111).

    ELE EXISTE PARA SER MEDIDO, e não para ponderar. Se o horizonte de cinco
    minutos dominar quase todo o observado, isso é evidência para um estudo
    futuro de ponderação temporal ou de velocidade — e é para REPORTAR, não
    para corrigir automaticamente (§200).
    """

    horizon_minutes: int
    shared_axes: int
    axis_count: int
    observed: float
    missing_penalty: float

    def __post_init__(self) -> None:
        if self.observed < 0:
            raise ValidationError(f"contribuição observada negativa: {self.observed!r}")
        if self.missing_penalty < 0:
            raise ValidationError(f"penalidade negativa: {self.missing_penalty!r}")

    @property
    def coverage(self) -> float:
        return self.shared_axes / self.axis_count

    @property
    def total(self) -> float:
        return self.observed + self.missing_penalty

    def as_canonical(self) -> dict[str, object]:
        from sports_intelligence.domain.retrieval.distance import distance_text

        return {
            "horizon_minutes": self.horizon_minutes,
            "missing_penalty": distance_text(self.missing_penalty),
            "observed": distance_text(self.observed),
            "shared_axes": self.shared_axes,
        }

    def __str__(self) -> str:
        return (
            f"{self.horizon_minutes}m: obs {self.observed:.4g} + inc "
            f"{self.missing_penalty:.4g} ({self.shared_axes}/{self.axis_count} eixos)"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryBreakdown:
    """As parcelas, com a abertura por horizonte junto.

    A ABERTURA POR HORIZONTE NÃO É DERIVÁVEL DO TOTAL, e é o que distingue
    «os dois jogos divergiram no último minuto» de «eles vinham divergindo há
    cinco». O total é o mesmo; a leitura é oposta.
    """

    observed_sum: float
    missing_penalty_sum: float
    cell_count: int
    shared_cells: int
    horizons: tuple[HorizonContribution, ...] = ()

    def __post_init__(self) -> None:
        if self.cell_count < 1:
            raise ValidationError("dissimilaridade temporal sobre um espaço sem células")
        if self.observed_sum < 0:
            raise ValidationError(f"soma de quadrados negativa: {self.observed_sum!r}")
        if self.missing_penalty_sum < 0:
            raise ValidationError(f"penalidade negativa: {self.missing_penalty_sum!r}")

    @property
    def unshared_cells(self) -> int:
        return self.cell_count - self.shared_cells

    @property
    def value(self) -> float:
        """`D_T`. As parcelas sobre o número FIXO de células."""
        return (self.observed_sum + self.missing_penalty_sum) / self.cell_count

    @property
    def observed_mse(self) -> float | None:
        """A discrepância MÉDIA de movimento no que foi observado.

        DIAGNÓSTICO, e nunca o ranking — o mesmo papel do `observed_mse` do
        PR-06.2, e pelo mesmo motivo: com `s` no denominador, um par com duas
        células e movimento idêntico teria média zero.
        """
        if self.shared_cells < 1:
            return None
        return self.observed_sum / self.shared_cells

    @property
    def penalty_share(self) -> float | None:
        """Que fração do numerador é incerteza temporal, e não movimento medido."""
        numerador = self.observed_sum + self.missing_penalty_sum
        if numerador <= 0:
            return None
        return self.missing_penalty_sum / numerador

    def horizon_share(self, horizon: int) -> float | None:
        """Que fração do OBSERVADO veio daquele horizonte (§199)."""
        if self.observed_sum <= 0:
            return None
        for contribuicao in self.horizons:
            if contribuicao.horizon_minutes == horizon:
                return contribuicao.observed / self.observed_sum
        return None

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "missing_penalty_sum": self.missing_penalty_sum,
            "observed_mse": self.observed_mse,
            "observed_sum": self.observed_sum,
            "penalty_share": self.penalty_share,
            "shared_cells": self.shared_cells,
            "unshared_cells": self.unshared_cells,
            "value": self.value,
            **{f"observed_{c.horizon_minutes}m": c.observed for c in self.horizons},
        }

    def __str__(self) -> str:
        return (
            f"D_T={self.value:.6g} = ({self.observed_sum:.6g} + "
            f"{self.missing_penalty_sum:.6g})/{self.cell_count}"
        )


@final
@dataclass(frozen=True, slots=True)
class TrajectoryDistanceDefinition:
    """O contrato da dissimilaridade temporal — janela, perfil, piso, conta."""

    profile: ResolvedTrajectoryProfile
    coverage_policy: TrajectoryCoveragePolicy = DEFAULT_TRAJECTORY_COVERAGE
    method: TrajectoryDistanceMethod = (
        TrajectoryDistanceMethod.MULTI_HORIZON_DISPLACEMENT_FIXED_PROFILE_IQR_PENALTY
    )
    missing_penalty_policy: str = MISSING_TRAJECTORY_CELL_PENALTY_SQUARED_IQR_V1
    missing_penalty: float = MISSING_CELL_PENALTY
    denominator_policy: str = FIXED_PROFILE_DENOMINATOR_V1
    float_semantics: str = FLOAT_SEMANTICS_V1

    def __post_init__(self) -> None:
        if self.missing_penalty < 0:
            raise ValidationError(
                f"penalidade {self.missing_penalty!r}: uma penalidade negativa faria a "
                "célula ausente APROXIMAR o candidato, e ausência premiada é a fraude "
                "que este módulo existe para impedir"
            )
        if self.profile.cell_count < 1:
            raise ValidationError(
                f"perfil de {self.profile.competition} sem células: o denominador fixo seria zero"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def cell_count(self) -> int:
        """`n = |H| · m`."""
        return self.profile.cell_count

    @property
    def is_metric(self) -> bool:
        """Ela NÃO é métrica, pelo mesmo motivo do PR-06.2.

        Uma representação incompleta comparada consigo mesma tem `D_T > 0`: as
        células que faltam continuam custando. Isso viola a identidade dos
        indiscerníveis, e basta para que nenhuma propriedade métrica possa ser
        assumida — a desigualdade triangular inclusive, que ninguém testou.
        """
        return False

    def incomplete_self_dissimilarity(self, shared_cells: int) -> float:
        """`D_T(x, x)` para um `x` com `shared_cells` células utilizáveis."""
        if shared_cells > self.cell_count or shared_cells < 0:
            raise ValidationError(f"{shared_cells} células sobre um espaço de {self.cell_count}")
        return (self.missing_penalty * (self.cell_count - shared_cells)) / self.cell_count

    # ------------------------------------------------------------- a conta --

    def evaluate(
        self, query: TrajectoryRepresentation, candidate: TrajectoryRepresentation
    ) -> TrajectoryBreakdown:
        """As parcelas do par, com a abertura por horizonte.

        AS DUAS REPRESENTAÇÕES PRECISAM SER DO MESMO ESPAÇO, e a conferência é
        por eixos e horizontes: duas máscaras do mesmo tamanho sobre ordens
        diferentes somariam pares que não se correspondem, e o número sairia
        plausível.
        """
        self._conferir(query, "query")
        self._conferir(candidate, "candidato")
        eixos = self.profile.axis_count
        termos_globais: list[float] = []
        contribuicoes: list[HorizonContribution] = []
        compartilhadas = 0

        for horizonte in self.profile.horizons:
            recorte = query.horizon_slice(horizonte)
            termos: list[float] = []
            juntos = 0
            for posicao in range(recorte.start, recorte.stop):
                if not (query.mask[posicao] and candidate.mask[posicao]):
                    continue
                dq = query.displacements[posicao]
                dc = candidate.displacements[posicao]
                if dq is None or dc is None:  # pragma: no cover — a máscara garantiu
                    raise ValidationError(
                        f"célula {posicao} marcada dos dois lados e sem deslocamento"
                    )
                delta = dq - dc
                termos.append(delta * delta)
                juntos += 1
            observado = math.fsum(termos)
            termos_globais.extend(termos)
            compartilhadas += juntos
            contribuicoes.append(
                HorizonContribution(
                    horizon_minutes=horizonte,
                    shared_axes=juntos,
                    axis_count=eixos,
                    observed=observado,
                    missing_penalty=self.missing_penalty * (eixos - juntos),
                )
            )

        return TrajectoryBreakdown(
            # `fsum` SOBRE TODOS OS TERMOS, e não a soma dos parciais por
            # horizonte: somar três somas já arredondadas é uma conta
            # diferente, e a impressão do resultado denunciaria a diferença
            # sem que ninguém soubesse de onde ela veio.
            observed_sum=math.fsum(termos_globais),
            missing_penalty_sum=self.missing_penalty * (self.cell_count - compartilhadas),
            cell_count=self.cell_count,
            shared_cells=compartilhadas,
            horizons=tuple(contribuicoes),
        )

    def assess(
        self, query: TrajectoryRepresentation, candidate: TrajectoryRepresentation
    ) -> TrajectoryCoverageAssessment:
        """A cobertura temporal do par, sob a política desta definição."""
        self._conferir(query, "query")
        self._conferir(candidate, "candidato")
        horizontes: list[HorizonCoverage] = []
        compartilhadas = 0
        for horizonte in self.profile.horizons:
            recorte = query.horizon_slice(horizonte)
            juntos = sum(
                1
                for posicao in range(recorte.start, recorte.stop)
                if query.mask[posicao] and candidate.mask[posicao]
            )
            compartilhadas += juntos
            horizontes.append(
                HorizonCoverage(
                    horizon_minutes=horizonte,
                    axis_count=self.profile.axis_count,
                    query_usable_axes=query.usable_in(horizonte),
                    candidate_usable_axes=candidate.usable_in(horizonte),
                    shared_axes=juntos,
                    policy=self.coverage_policy,
                )
            )
        return TrajectoryCoverageAssessment(
            cell_count=self.cell_count,
            axis_count=self.profile.axis_count,
            query_usable_cells=query.usable_count,
            candidate_usable_cells=candidate.usable_count,
            shared_cells=compartilhadas,
            horizons=tuple(horizontes),
            policy=self.coverage_policy,
        )

    def _conferir(self, representacao: TrajectoryRepresentation, lado: str) -> None:
        if representacao.feature_keys != self.profile.feature_keys:
            raise ValidationError(
                f"a representação do {lado} percorre outros eixos: os deslocamentos "
                "seriam somados em pares que não se correspondem",
                context={"side": lado},
            )
        if representacao.horizons != self.profile.horizons:
            raise ValidationError(
                f"a representação do {lado} tem horizontes {representacao.horizons} e o "
                f"perfil declara {self.profile.horizons}",
                context={"side": lado},
            )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_DISTANCE_FINGERPRINT_ALGORITHM,
            "cell_count": self.cell_count,
            "coverage_policy_fingerprint": self.coverage_policy.fingerprint,
            "denominator_policy": self.denominator_policy,
            "feature_order": list(self.profile.feature_keys),
            "float_semantics": self.float_semantics,
            "horizon_order": list(self.profile.horizons),
            "method": self.method.value,
            "missing_penalty": repr(self.missing_penalty),
            "missing_penalty_policy": self.missing_penalty_policy,
            "representation": DISPLACEMENT_REPRESENTATION_V1,
            "trajectory_profile_fingerprint": self.profile.fingerprint,
            "window_fingerprint": self.profile.profile.window.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return (
            f"{self.method.value}/{self.cell_count} células p={self.missing_penalty!r} "
            f"[{self.fingerprint[:12]}]"
        )


def horizon_summary(breakdown: TrajectoryBreakdown) -> Sequence[str]:
    """As linhas do resumo por horizonte — para a CLI e para o relatório."""
    linhas = [str(breakdown)]
    for contribuicao in breakdown.horizons:
        parcela = breakdown.horizon_share(contribuicao.horizon_minutes)
        sufixo = "" if parcela is None else f"  ({parcela:.0%} do observado)"
        linhas.append(f"  {contribuicao}{sufixo}")
    return linhas
