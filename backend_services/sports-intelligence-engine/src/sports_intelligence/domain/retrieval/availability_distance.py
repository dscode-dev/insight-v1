"""A dissimilaridade ciente de disponibilidade — e por que ela cobra a ausência.

                Σ_{i∈S} (qᵢ - cᵢ)²   +   p·(m - s)
    D_AA(q,c) = ───────────────────────────────────       p = 1
                                m

TRÊS DECISÕES, E CADA UMA IMPEDE UMA FRAUDE DIFERENTE.

**O DENOMINADOR É `m`, E NUNCA `s`.** Esta é a decisão central. Com `s` no
denominador, um candidato que compartilha duas dimensões e acerta as duas teria
média zero e ganharia de um que compartilha vinte e erra pouco em uma. O
denominador fixo faz com que o que falta continue no divisor — a ausência não
some da conta por ter sumido do numerador.

    denominador fixo    dois candidatos com coberturas diferentes produzem
                        números na MESMA escala, e comparar os dois significa
                        alguma coisa
    denominador móvel   cada candidato mede uma grandeza diferente, e a
                        comparação entre eles é aritmética sobre unidades
                        distintas

**A PENALIDADE É `p = 1` POR EIXO AUSENTE, EM UNIDADE DE IQR².** Os eixos
robustos estão em `(x - mediana) / IQR`, então uma diferença de `1` é uma
diferença de um IQR da competição. Cobrar `1` por eixo desconhecido diz:

    «não sei o que havia aqui, e trato isso como se houvesse uma
     discrepância de um IQR»

Isso NÃO é preencher com zero. Zero é a MEDIANA da competição — imputá-lo
afirmaria que o estado ausente era típico, que é uma afirmação forte sobre um
dado que não existe, e deixaria o candidato incompleto artificialmente PERTO de
qualquer query mediana. A penalidade faz o contrário: ela empurra para longe.

**EVIDÊNCIA REAL SUBSTITUI INCERTEZA, E PODE PIORAR O NÚMERO.** Quando um eixo
ausente passa a ser observado, a contribuição dele deixa de ser `1` e passa a
ser `δ²`:

    |δ| < 1     o candidato melhora — a evidência era favorável
    |δ| = 1     empate exato com a incerteza
    |δ| > 1     o candidato PIORA — a evidência era desfavorável

O terceiro caso não é defeito, e não é para ser evitado: descobrir que dois
estados diferem em dois IQRs num eixo é informação, e ela tem de valer mais que
a suposição que ocupava aquele lugar. Uma penalidade alta demais tornaria o
desconhecido sempre pior que qualquer evidência; uma baixa demais tornaria o
desconhecido sempre melhor. `p = 1` é o ponto em que a troca é neutra na
unidade em que os eixos vivem.

**DOIS AUSENTES NÃO SÃO UM ACORDO.** Se query e candidato não têm o eixo, ele
não é compartilhado e recebe a penalidade igual. Dois desconhecidos coincidirem
não é evidência de igualdade — é ausência de evidência, e a conta trata as duas
do mesmo jeito.

O QUE ISTO NÃO É:

    não é métrica          `D_AA(x,x) > 0` quando `x` é incompleto, porque a
                           incerteza dos eixos que `x` não tem continua na
                           conta. Uma função de distância com auto-distância
                           positiva não é métrica, e o nome diz isso
    não é confiança        `PenaltyShare` é evidência, e transformá-la em
                           `confiança = 0,82` é do PR-06.7
    não tem pesos          nem alfa, nem beta, nem gama, nem por família, nem
                           aprendido. Todo eixo compartilhado vale 1, e todo
                           eixo ausente custa 1
    não tem epsilon        nem suavização, nem penalidade por feature, nem
                           penalidade por família

A SEMÂNTICA NUMÉRICA É A MESMA DO PR-06.1 — `IEEE754_FLOAT64_FSUM_V1`. Inventar
outra aqui tornaria os dois resultados incomparáveis por um motivo que não tem
nada a ver com ausência.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.availability import count as _contar
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    AvailabilityCoveragePolicy,
    CoverageAssessment,
)
from sports_intelligence.domain.retrieval.distance import FLOAT_SEMANTICS_V1
from sports_intelligence.domain.retrieval.profile import (
    MissingPolicy,
    ResolvedRetrievalProfile,
    WeightPolicy,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

AVAILABILITY_DISTANCE_FINGERPRINT_ALGORITHM: Final[str] = "availability-aware-distance-sha256-v1"

#: A política de penalidade da V1. O nome carrega a UNIDADE — `IQR²` — porque
#: «penalidade = 1» sem unidade não significa nada: um por cento, um gol e um
#: IQR são todos «1».
MISSING_AXIS_PENALTY_SQUARED_IQR_V1: Final[str] = "MISSING_AXIS_PENALTY_SQUARED_IQR_V1"

#: A política do denominador. Ela é NOMEADA e entra na impressão porque é a
#: decisão que impede a fraude aritmética — ver o cabeçalho.
FIXED_PROFILE_DENOMINATOR_V1: Final[str] = "FIXED_PROFILE_DENOMINATOR_V1"

#: `p`. Uma unidade quadrática de incerteza em escala IQR.
MISSING_AXIS_PENALTY: Final[float] = 1.0


@final
class AvailabilityDistanceMethod(StrEnum):
    """Como a dissimilaridade ciente de ausência é calculada. FECHADO."""

    #: `(Σ_S δ² + p·u) / m`, pesos iguais, denominador fixo no perfil.
    AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY = "AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY_V1"


@final
@dataclass(frozen=True, slots=True)
class DistanceBreakdown:
    """As três parcelas, preservadas separadamente (§31).

    ELAS NÃO SÃO DERIVÁVEIS DO TOTAL. `D = 0,4` pode ser discrepância pura
    sobre o perfil inteiro ou incerteza pura sobre metade dele, e as duas
    coisas significam coisas opostas sobre a qualidade do vizinho. Guardar só o
    total apagaria essa diferença — que é justamente o que este PR existe para
    medir.
    """

    observed_squared_sum: float
    missing_penalty_sum: float
    profile_axis_count: int
    shared_count: int

    def __post_init__(self) -> None:
        if self.profile_axis_count < 1:
            raise ValidationError("dissimilaridade sobre um perfil sem eixos")
        if self.observed_squared_sum < 0:
            raise ValidationError(f"soma de quadrados negativa: {self.observed_squared_sum!r}")
        if self.missing_penalty_sum < 0:
            raise ValidationError(f"penalidade negativa: {self.missing_penalty_sum!r}")

    @property
    def unshared_count(self) -> int:
        return self.profile_axis_count - self.shared_count

    @property
    def value(self) -> float:
        """`D_AA`. A soma das parcelas sobre o número FIXO de eixos."""
        return (self.observed_squared_sum + self.missing_penalty_sum) / self.profile_axis_count

    @property
    def observed_mse(self) -> float | None:
        """`Σ_S δ² / s`. A discrepância MÉDIA no que foi de fato observado.

        ELA É DIAGNÓSTICO, E NUNCA O RANKING (§33). É o número que responde
        «quão parecidos eles são no que dá para comparar?» — e um candidato com
        MSE baixíssimo sobre quatro eixos de vinte é exatamente o caso que o
        denominador fixo existe para não premiar.

        `None` QUANDO `s = 0`: uma média de zero termos não é zero.
        """
        if self.shared_count < 1:
            return None
        return self.observed_squared_sum / self.shared_count

    @property
    def penalty_share(self) -> float | None:
        """Que fração do numerador é INCERTEZA, e não discrepância medida.

        UM VIZINHO DE 95 % DE INCERTEZA NÃO É UM VIZINHO DE 5 % (§84). Os dois
        podem ter o mesmo `D`, e o primeiro está dizendo «quase não te medi».

        `None` QUANDO O NUMERADOR É ZERO — o par é idêntico e completo, e não
        há de que tirar fração.
        """
        numerador = self.observed_squared_sum + self.missing_penalty_sum
        if numerador <= 0:
            return None
        return self.missing_penalty_sum / numerador

    def __str__(self) -> str:
        return (
            f"D={self.value:.6g} = ({self.observed_squared_sum:.6g} + "
            f"{self.missing_penalty_sum:.6g})/{self.profile_axis_count}"
        )


@final
@dataclass(frozen=True, slots=True)
class AvailabilityAwareDistanceDefinition:
    """O contrato da dissimilaridade — perfil, piso e penalidade, juntos.

    A POLÍTICA DE COBERTURA ENTRA NA IMPRESSÃO, e não só a fórmula. Dois
    números calculados pela mesma fórmula sob pisos diferentes descrevem
    populações de candidatos diferentes: o de piso baixo inclui pares que o de
    piso alto recusou, e comparar os dois rankings sem saber disso compararia
    duas coisas.
    """

    profile: ResolvedRetrievalProfile
    coverage_policy: AvailabilityCoveragePolicy = DEFAULT_COVERAGE_POLICY
    method: AvailabilityDistanceMethod = (
        AvailabilityDistanceMethod.AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY
    )
    missing_penalty_policy: str = MISSING_AXIS_PENALTY_SQUARED_IQR_V1
    missing_penalty: float = MISSING_AXIS_PENALTY
    denominator_policy: str = FIXED_PROFILE_DENOMINATOR_V1
    float_semantics: str = FLOAT_SEMANTICS_V1

    def __post_init__(self) -> None:
        if self.profile.base.weight_policy is not WeightPolicy.EQUAL:
            raise ValidationError(
                f"perfil com ponderação {self.profile.base.weight_policy.value}: o "
                "PR-06.2 tem pesos iguais por decisão — ponderação é do PR-06.5, e "
                "um peso por eixo muda o que a distância mede sem mudar o nome dela"
            )
        if self.profile.base.missing_policy is not MissingPolicy.AVAILABILITY_AWARE:
            raise ValidationError(
                f"perfil com política de ausência "
                f"{self.profile.base.missing_policy.value}: esta definição cobra a "
                "ausência, e um perfil de CASO COMPLETO declara que ela nunca chega "
                "aqui — as duas afirmações não podem valer ao mesmo tempo",
                context={"missing_policy": self.profile.base.missing_policy.value},
            )
        if self.missing_penalty < 0:
            raise ValidationError(
                f"penalidade {self.missing_penalty!r}: uma penalidade negativa faria "
                "o eixo ausente APROXIMAR o candidato, e ausência premiada é a fraude "
                "que este módulo existe para impedir"
            )
        if self.profile.axis_count < 1:
            raise ValidationError(
                f"perfil de {self.profile.competition} sem eixos: o denominador fixo seria zero"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def axis_count(self) -> int:
        return self.profile.axis_count

    @property
    def is_metric(self) -> bool:
        """Ela NÃO é métrica, e a propriedade existe para dizer isso.

        Ver `incomplete_self_dissimilarity`: um vetor incompleto comparado
        consigo mesmo tem dissimilaridade positiva. Isso viola a identidade dos
        indiscerníveis, e basta para que nenhuma propriedade métrica possa ser
        assumida — inclusive as que ninguém testou.
        """
        return False

    def incomplete_self_dissimilarity(self, shared_count: int) -> float:
        """`D_AA(x, x)` para um `x` que só tem `shared_count` eixos.

        ELA EXISTE PARA SER CITADA NO RELATÓRIO E NO TESTE. `D(x,x) = u/m > 0`
        é a prova mais curta de que esta função não é métrica — e tê-la como
        método impede que alguém a redescubra como «bug».
        """
        if shared_count > self.axis_count or shared_count < 0:
            raise ValidationError(f"{shared_count} eixos sobre um perfil de {self.axis_count}")
        return (self.missing_penalty * (self.axis_count - shared_count)) / self.axis_count

    # ------------------------------------------------------------- a conta --

    def evaluate(
        self,
        query: Sequence[float | None],
        candidate: Sequence[float | None],
        shared: Sequence[bool],
    ) -> DistanceBreakdown:
        """As três parcelas do par. A máscara decide quais eixos entram.

        ELA RECEBE A MÁSCARA, e é a diferença de assinatura em relação ao
        PR-06.1. Lá a ausência não podia chegar; aqui ela é parte do cálculo, e
        um cálculo que não visse a máscara teria de adivinhar o que fazer com
        `None`.

        OS VALORES FORA DA MÁSCARA NÃO SÃO LIDOS. Um número presente num eixo
        marcado como ausente é ignorado — e `availability_mask` já teria parado
        antes, porque essa combinação é contradição.
        """
        if len(query) != self.axis_count or len(candidate) != self.axis_count:
            raise ValidationError(
                f"vetores de {len(query)} e {len(candidate)} contra um perfil de "
                f"{self.axis_count} eixos: a soma percorreria pares que não existem",
                context={
                    "candidate": str(len(candidate)),
                    "profile": str(self.axis_count),
                    "query": str(len(query)),
                },
            )
        if len(shared) != self.axis_count:
            raise ValidationError(
                f"máscara de {len(shared)} posições contra um perfil de "
                f"{self.axis_count} eixos: ela é de outro espaço"
            )
        termos: list[float] = []
        for indice, marcado in enumerate(shared):
            if not marcado:
                continue
            q = query[indice]
            c = candidate[indice]
            if q is None or c is None or not math.isfinite(q) or not math.isfinite(c):
                raise ValidationError(
                    f"eixo {self.profile.feature_keys[indice]!r} marcado como "
                    f"compartilhado e sem número finito dos dois lados: q={q!r} "
                    f"c={c!r}. A máscara e os valores discordam",
                    context={"axis": self.profile.feature_keys[indice]},
                )
            delta = q - c
            termos.append(delta * delta)
        compartilhados = _contar(shared)
        return DistanceBreakdown(
            # `fsum` PELO MESMO MOTIVO DO PR-06.1 — garantia de contrato da
            # linguagem, e não um defeito observado. Ver `distance.py`.
            observed_squared_sum=math.fsum(termos),
            missing_penalty_sum=self.missing_penalty * (self.axis_count - compartilhados),
            profile_axis_count=self.axis_count,
            shared_count=compartilhados,
        )

    def assess(
        self, *, query_available: int, candidate_available: int, shared: int
    ) -> CoverageAssessment:
        """A cobertura do par, sob a política desta definição."""
        return CoverageAssessment(
            profile_axis_count=self.axis_count,
            query_available_count=query_available,
            candidate_available_count=candidate_available,
            shared_count=shared,
            policy=self.coverage_policy,
        )

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        """Tudo que muda o número — e por isso o piso entra (§48)."""
        return {
            "algorithm": AVAILABILITY_DISTANCE_FINGERPRINT_ALGORITHM,
            "coverage_policy_fingerprint": self.coverage_policy.fingerprint,
            "denominator_policy": self.denominator_policy,
            "feature_order": list(self.profile.feature_keys),
            "float_semantics": self.float_semantics,
            "method": self.method.value,
            "missing_penalty": repr(self.missing_penalty),
            "missing_penalty_policy": self.missing_penalty_policy,
            "missing_policy": self.profile.base.missing_policy.value,
            "resolved_profile_fingerprint": self.profile.fingerprint,
            "weight_policy": self.profile.base.weight_policy.value,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return (
            f"{self.method.value}/{self.axis_count} eixos p={self.missing_penalty!r} "
            f"[{self.fingerprint[:12]}]"
        )
