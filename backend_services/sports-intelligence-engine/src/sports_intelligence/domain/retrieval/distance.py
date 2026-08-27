"""A dissimilaridade do baseline — L2 ao quadrado, caso completo, exata.

    d²(q, c) = Σ (qᵢ - cᵢ)²      para todo i no perfil resolvido

SEM RAIZ, E O NOME DIZ ISSO. `sqrt` é monotônica nos reais não negativos, então

    d₁² < d₂²   ⟺   d₁ < d₂

e o RANKING é o mesmo. O que muda é o que se pode afirmar do número: `d²` NÃO é
uma métrica — ela não satisfaz a desigualdade triangular. Chamá-la de «distância
euclidiana» e depois usar propriedades métricas dela é o erro que este módulo
existe para não permitir; o nome aqui é **dissimilaridade L2 ao quadrado**.

    o que vale        d(q,q) = 0 · d(q,c) ≥ 0 · d(q,c) = d(c,q)
    o que NÃO vale    d(a,c) ≤ d(a,b) + d(b,c)

PESOS IGUAIS, E ISSO É UMA DECISÃO. Não há alfa, beta, gama, peso por família
nem peso aprendido. Todo eixo do perfil vale 1 — e o perfil já garante que
todos estão na mesma escala robusta por competição, que é o que torna a soma
legítima.

A SOMA É `math.fsum`, E O MOTIVO NÃO É O QUE PARECE. A justificativa fácil
seria «`sum` depende da ordem e `fsum` não» — e ela é FALSA neste interpretador:
o CPython 3.12 passou a somar `float` com compensação de Neumaier, e em duzentas
mil amostras de oito termos nas magnitudes deste dataset os dois concordam em
todos os casos, inclusive com os termos invertidos.

O MOTIVO VERDADEIRO É DE CONTRATO. A exatidão de `fsum` é uma garantia
DOCUMENTADA da linguagem: ela devolve o `float64` mais próximo da soma real dos
termos, e isso vale em qualquer implementação e em qualquer versão. A
compensação de `sum` é um detalhe de implementação do CPython — não está na
especificação, não existia antes da 3.12, e não se pode contar com ela noutro
interpretador.

    a divergência EXISTE e é demonstrável, mas só com razões de escala
    extremas (1e18 contra 1e-18) que features normalizadas robustas — que
    vivem na casa de ±10 — nunca produzem. Escolher `fsum` aqui não é
    consertar um defeito observado: é não depender de um detalhe.

A ORDEM DOS EIXOS É FIXA de qualquer jeito — a do perfil resolvido —, e é ela
que garante que os PARES `(qᵢ, cᵢ)` são os mesmos dos dois lados.

NÃO FINITO É CORRUPÇÃO, e não ausência. O dataset normalizado recusa `NaN` e
infinito na escrita (ADR-0040); um deles chegando aqui significa invariante
quebrado a montante, e tratá-lo como «candidato sem valor» esconderia o defeito
atrás de uma ausência que parece normal.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.profile import (
    MissingPolicy,
    ResolvedRetrievalProfile,
    WeightPolicy,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

DISTANCE_FINGERPRINT_ALGORITHM: Final[str] = "distance-definition-sha256-v1"

#: A semântica de ponto flutuante desta definição. Ela é VERSIONADA porque é
#: parte do contrato: uma soma com outra garantia numérica é outra definição de
#: distância, e a impressão precisa denunciar isso mesmo quando os números
#: coincidem na prática.
FLOAT_SEMANTICS_V1: Final[str] = "IEEE754_FLOAT64_FSUM_V1"


@final
class DistanceMethod(StrEnum):
    """Como a dissimilaridade é calculada. Catálogo FECHADO.

    UM MEMBRO SÓ. Cosseno, Manhattan, Mahalanobis e distância aprendida não
    estão aqui — e a ausência é o ponto: o método entra na impressão do
    resultado, e um método novo é um resultado novo.
    """

    #: `Σ (qᵢ - cᵢ)²` sobre o perfil resolvido, pesos iguais, caso completo.
    EXACT_SQUARED_L2_COMPLETE_CASE = "EXACT_SQUARED_L2_COMPLETE_CASE_V1"


@final
@dataclass(frozen=True, slots=True)
class DistanceDefinition:
    """O contrato da dissimilaridade, amarrado ao perfil que ela percorre.

    ELA CARREGA O PERFIL RESOLVIDO, e não só o nome do método. «L2 ao quadrado»
    sem os eixos não identifica nada: a mesma fórmula sobre catorze eixos e
    sobre vinte e nove produz números que não se comparam, e os dois pareceriam
    a mesma grandeza.
    """

    profile: ResolvedRetrievalProfile
    method: DistanceMethod = DistanceMethod.EXACT_SQUARED_L2_COMPLETE_CASE
    float_semantics: str = FLOAT_SEMANTICS_V1

    def __post_init__(self) -> None:
        if self.profile.base.weight_policy is not WeightPolicy.EQUAL:
            raise ValidationError(
                f"perfil com ponderação {self.profile.base.weight_policy.value}: o "
                "baseline do PR-06.1 tem pesos iguais por decisão, e um peso por eixo "
                "muda o que a distância mede sem mudar o nome dela"
            )
        if self.profile.base.missing_policy is not MissingPolicy.COMPLETE_CASE:
            raise ValidationError(
                f"perfil com política de ausência "
                f"{self.profile.base.missing_policy.value}: distância ciente de "
                "ausência é do PR-06.2, e improvisá-la aqui produziria um número que "
                "parece uma resposta"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def axis_count(self) -> int:
        return self.profile.axis_count

    @property
    def is_squared(self) -> bool:
        """Se o valor devolvido é `d²`, e não `d`.

        ELE EXISTE PARA SER PERGUNTADO por quem vai imprimir o número. Um
        relatório que rotule `d²` como «distância» convida à comparação com
        limiares euclidianos que não valem.
        """
        return True

    # ------------------------------------------------------------- a conta --

    def evaluate(self, query: Sequence[float], candidate: Sequence[float]) -> float:
        """`Σ (qᵢ - cᵢ)²`. Os dois vetores já são de CASO COMPLETO.

        ELE NÃO RECEBE MÁSCARA, e a assinatura é a garantia: quem chama já
        decidiu que o par é comparável. Um vetor com ausência não tem como
        entrar aqui — e essa é a diferença entre um baseline de caso completo e
        um que finge sê-lo.
        """
        if len(query) != self.axis_count or len(candidate) != self.axis_count:
            raise ValidationError(
                f"vetores de {len(query)} e {len(candidate)} contra um perfil de "
                f"{self.axis_count} eixos: a soma percorreria pares que não existem, "
                "ou deixaria eixos de fora sem dizer",
                context={
                    "query": str(len(query)),
                    "candidate": str(len(candidate)),
                    "profile": str(self.axis_count),
                },
            )
        termos: list[float] = []
        for indice, (q, c) in enumerate(zip(query, candidate, strict=True)):
            if not math.isfinite(q) or not math.isfinite(c):
                raise ValidationError(
                    f"valor não finito no eixo {self.profile.feature_keys[indice]!r}: "
                    f"q={q!r} c={c!r}. O dataset normalizado recusa NaN e infinito na "
                    "escrita, então isto é invariante quebrado a montante — e não a "
                    "ausência de um candidato",
                    context={"axis": self.profile.feature_keys[indice]},
                )
            delta = q - c
            termos.append(delta * delta)
        # `fsum` E NÃO `sum`: a soma exata dos termos, independente da ordem em
        # que eles chegaram. Ver o cabeçalho.
        return math.fsum(termos)

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": DISTANCE_FINGERPRINT_ALGORITHM,
            "feature_order": list(self.profile.feature_keys),
            "float_semantics": self.float_semantics,
            "method": self.method.value,
            "missing_policy": self.profile.base.missing_policy.value,
            "resolved_profile_fingerprint": self.profile.fingerprint,
            "weight_policy": self.profile.base.weight_policy.value,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"{self.method.value}/{self.axis_count} eixos [{self.fingerprint[:12]}]"


def distance_text(value: float) -> str:
    """A representação canônica de uma distância, para impressão e relatório.

    ELA É `repr`, E NÃO UMA FORMATAÇÃO COM CASAS FIXAS. `repr(float)` em Python
    3 devolve o texto mais curto que volta ao MESMO `float64`, então ele é uma
    identidade — enquanto `f"{x:.6f}"` colapsaria dois números diferentes na
    mesma linha do relatório e faria um empate aparecer onde não há.
    """
    if not math.isfinite(value):
        raise ValidationError(f"distância não finita: {value!r}")
    return repr(value)
