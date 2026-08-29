"""A política de ponderação — e por que `lambda` é semântica, e não ajuste.

`lambda` ENTRA NA IMPRESSÃO. Trocar `1,0` por `2,0` não é «afinar um número»: é
outra semântica de ponderação, que produz outra concentração sobre exatamente os
mesmos vizinhos e as mesmas distâncias. Um resultado agregado sob `lambda = 1` e
outro sob `lambda = 2` não se comparam, e a impressão precisa dizer isso antes
que alguém os some.

E ELE NUNCA É IMPLÍCITO. Não há `lam=1.0` num corpo de função em lugar nenhum:
o valor vem sempre da política, porque um padrão escondido é um parâmetro que
ninguém declarou e que ninguém consegue auditar depois.

## Estado e trajetória são políticas SEPARADAS

Não porque seja elegante, mas porque as distribuições de distância são
diferentes. `D_state` é uma média sobre `m` eixos; `D_T` é uma média sobre
`n = 3m` células, com penalidade por célula ausente. O mesmo `lambda` sobre as
duas produziria concentrações diferentes por acidente de escala, e não por
decisão.

## Como `lambda` foi escolhido — e como NÃO foi

Só pela GEOMETRIA do retrieval: distribuição de `N_eff`, massa do topo,
concentração. Nunca por desfecho: escolher `lambda` porque ele «acerta mais
gols» seria vazar a camada de inferência para dentro da agregação, e a partir
daí a agregação deixaria de ser uma transformação e passaria a ser um modelo
não declarado.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.aggregation.kernel import (
    IEEE754_FLOAT64_FSUM_V1,
    SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1,
    assert_lambda,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

WEIGHTING_FINGERPRINT_ALGORITHM: Final[str] = "distance-weighting-policy-sha256-v1"

#: Os núcleos disponíveis. Dois, e o segundo é para os goldens.
EXPONENTIAL_KERNEL_V1: Final[str] = "EXPONENTIAL_KERNEL_V1"
UNIFORM_WEIGHTING_BASELINE_V1: Final[str] = "UNIFORM_WEIGHTING_BASELINE_V1"

#: Os nomes das políticas de produção.
STATE_DISTANCE_WEIGHTING_V1: Final[str] = "STATE_DISTANCE_WEIGHTING_V1"
TRAJECTORY_DISTANCE_WEIGHTING_V1: Final[str] = "TRAJECTORY_DISTANCE_WEIGHTING_V1"

#: O `lambda` SELECIONADO para o estado, e como ele foi escolhido.
#:
#: DUAS EVIDÊNCIAS INDEPENDENTES APONTAM PARA O MESMO LUGAR, e nenhuma delas
#: olhou desfecho:
#:
#:   1. a GEOMETRIA do top-K. O espalhamento mediano `d_max - d_min` num
#:      top-20 real é 0,2710. Para que o vizinho mais distante receba um décimo
#:      da massa do mais próximo — `exp(lambda . espalhamento) = 10` —, é
#:      preciso `lambda = ln(10)/0,2710 = 8,50`.
#:
#:   2. a VARREDURA de concentração. Em `lambda = 8`, `N_eff` mediano cai para
#:      12,34 de 20 (62% de K) com peso máximo 0,115 contra 0,05 do uniforme.
#:      Nem quase uniforme, nem dominado por um vizinho — os dois extremos que
#:      o contrato manda evitar.
#:
#: A PRIMEIRA GRADE PARAVA EM 4,0 e mostrava `N_eff ~ K` em toda parte. A leitura
#: fácil seria «nenhum lambda diferencia»; a medição do espalhamento mostrou que
#: a grade é que não alcançava a resposta.
SELECTED_STATE_LAMBDA: Final[float] = 8.0

#: E o da trajetória, MAIOR — porque a escala da distância é outra.
#:
#: `D_T` é uma média sobre `n = 3m` células, e o espalhamento mediano de um
#: top-20 real é 0,1434 — quase metade do de estado. Pela mesma conta,
#: `ln(10)/0,1434 = 16,06`; pela varredura, `lambda = 16` dá `N_eff` mediano de
#: 13,66 de 20 (68% de K), concentração comparável à do estado em `lambda = 8`.
#:
#: É ESTA A EVIDÊNCIA DE QUE AS DUAS POLÍTICAS PRECISAM SER SEPARADAS. Aplicar
#: `lambda = 8` à trajetória deixaria `N_eff` em 16,50 de 20 — quase uniforme —,
#: e o mesmo número produziria comportamentos diferentes nos dois caminhos por
#: acidente de escala.
SELECTED_TRAJECTORY_LAMBDA: Final[float] = 16.0


@final
class RetrievalKind(StrEnum):
    """A que recuperação a política se aplica. FECHADO.

    ELE EXISTE PARA IMPEDIR A FUSÃO. Uma política de estado aplicada a vizinhos
    de trajetória produziria números plausíveis sobre outra grandeza, e o
    catálogo fechado é o que faz a troca falhar alto em vez de sair calada.
    """

    STATE = "STATE"
    TRAJECTORY = "TRAJECTORY"


@final
@dataclass(frozen=True, slots=True)
class DistanceWeightingPolicy:
    """Como a dissimilaridade exata vira massa relativa.

    A IMPRESSÃO DA DISTÂNCIA ENTRA AQUI. Os pesos são função da dissimilaridade,
    e a dissimilaridade é definida por uma `DistanceDefinition` com impressão
    própria; sem amarrá-la, dois agregados calculados sob réguas diferentes
    teriam a mesma identidade de política.
    """

    name: str
    version: int
    kind: RetrievalKind
    kernel: str
    lam: float
    distance_definition_fingerprint: str
    normalization: str = SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1
    numeric_policy: str = IEEE754_FLOAT64_FSUM_V1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("política de ponderação sem nome")
        if self.kernel not in (EXPONENTIAL_KERNEL_V1, UNIFORM_WEIGHTING_BASELINE_V1):
            raise ValidationError(f"núcleo desconhecido: {self.kernel}")
        if self.kernel == EXPONENTIAL_KERNEL_V1:
            assert_lambda(self.lam)
        elif self.lam != 0.0:
            raise ValidationError(
                f"a linha de base uniforme não usa lambda, e recebeu {self.lam!r}: "
                "guardá-lo daria a impressão de que ele influencia o resultado"
            )
        if self.normalization != SHIFTED_EXPONENTIAL_MIN_DISTANCE_V1:
            raise ValidationError(
                f"normalização {self.normalization}: a V1 congelou a forma deslocada "
                "pelo mínimo de distância, e trocá-la exigiria nova versão"
            )

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def is_uniform(self) -> bool:
        return self.kernel == UNIFORM_WEIGHTING_BASELINE_V1

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": WEIGHTING_FINGERPRINT_ALGORITHM,
            "distance_definition_fingerprint": self.distance_definition_fingerprint,
            "kernel": self.kernel,
            "kind": self.kind.value,
            # `repr` DO FLOAT, e não uma formatação truncada: `lambda` é parte
            # da identidade, e duas políticas que diferem no décimo segundo
            # dígito produzem pesos diferentes.
            "lambda": repr(float(self.lam)),
            "name": self.name,
            "normalization": self.normalization,
            "numeric_policy": self.numeric_policy,
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "kernel": self.kernel,
            "kind": self.kind.value,
            "lambda": self.lam,
            "normalization": self.normalization,
        }

    def __str__(self) -> str:
        if self.is_uniform:
            return f"{self.identity} · uniforme [{self.fingerprint[:12]}]"
        return f"{self.identity} · exp(-{self.lam:g}·d) [{self.fingerprint[:12]}]"


def state_weighting(
    *,
    lam: float = SELECTED_STATE_LAMBDA,
    distance_definition_fingerprint: str,
    version: int = 1,
) -> DistanceWeightingPolicy:
    """A política de ESTADO, com o `lambda` SELECIONADO por medição.

    O PADRÃO AQUI NÃO É UM PADRÃO ESCONDIDO (§20). Ele é uma constante nomeada,
    documentada com as duas medições que a produziram, e entra na impressão —
    trocá-la muda a identidade da política. O que o §20 proíbe é um `1.0`
    literal no corpo de uma função, sem nome e sem justificativa.
    """
    return DistanceWeightingPolicy(
        name=STATE_DISTANCE_WEIGHTING_V1,
        version=version,
        kind=RetrievalKind.STATE,
        kernel=EXPONENTIAL_KERNEL_V1,
        lam=lam,
        distance_definition_fingerprint=distance_definition_fingerprint,
    )


def trajectory_weighting(
    *,
    lam: float = SELECTED_TRAJECTORY_LAMBDA,
    distance_definition_fingerprint: str,
    version: int = 1,
) -> DistanceWeightingPolicy:
    """A de TRAJETÓRIA, versionada de forma independente (§21).

    O `lambda` É O DOBRO DO DE ESTADO, e isso é medição e não simetria: o
    espalhamento das distâncias de trajetória é cerca de metade do de estado.
    """
    return DistanceWeightingPolicy(
        name=TRAJECTORY_DISTANCE_WEIGHTING_V1,
        version=version,
        kind=RetrievalKind.TRAJECTORY,
        kernel=EXPONENTIAL_KERNEL_V1,
        lam=lam,
        distance_definition_fingerprint=distance_definition_fingerprint,
    )


def uniform_baseline(
    *, kind: RetrievalKind, distance_definition_fingerprint: str
) -> DistanceWeightingPolicy:
    """A linha de base do §25 — para goldens, e não para produção.

    ELA EXISTE PARA PROVAR `N_eff = k`. Sob pesos iguais o tamanho efetivo tem
    de dar exatamente o número de vizinhos, e essa igualdade é o que demonstra
    que `N_eff` não depende do núcleo exponencial para estar certo.
    """
    return DistanceWeightingPolicy(
        name=UNIFORM_WEIGHTING_BASELINE_V1,
        version=1,
        kind=kind,
        kernel=UNIFORM_WEIGHTING_BASELINE_V1,
        lam=0.0,
        distance_definition_fingerprint=distance_definition_fingerprint,
    )
