"""Quais eixos a trajetória usa — os MESMOS do estado, e por quê.

    Axes_trajectory = Axes_state-AA

E ISSO NÃO É ECONOMIA DE DIGITAÇÃO. É a condição para que a comparação entre
o PR-06.2 e o PR-06.3 signifique alguma coisa: se os eixos também mudassem, a
diferença entre os dois resultados mediria duas coisas ao mesmo tempo — a
mudança de espaço e a mudança de pergunta —, e não haveria como separá-las.

    o que muda   NÍVEL vs MOVIMENTO
    o que NÃO    quais dimensões, quais competições, quais candidatos

O PERFIL RESOLVIDO VEM PRONTO, do `ROBUST_AVAILABILITY_AWARE_EXACT_V1`. Este
módulo não reimplementa a seleção: ele a RECEBE e acrescenta as três decisões
que são da trajetória — a janela, a representação e a ordem dos horizontes.

NENHUM EIXO `PASS_THROUGH` ENTRA (§37). Placar, superioridade numérica, cartões
e substituições não estão no perfil robusto ajustado de hoje, e acrescentá-los
aqui misturaria «trajetória» com «espaço de features novo» — que é outro PR e
outra discussão.

O MERCADO CONTINUA FORA, e o motivo já está medido (§38): uma cotação sem
`observed_at` é `UNKNOWN` para a guarda temporal, o caminho de ingestão não tem
papel semântico para esse carimbo, e os eixos de mercado nunca saem `FITTED`.
Consertar isso é ingestão, e não recuperação.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    MissingPolicy,
    ResolvedRetrievalProfile,
    RetrievalFeatureProfile,
    WeightPolicy,
)
from sports_intelligence.domain.retrieval.trajectory import (
    DISPLACEMENT_REPRESENTATION_V1,
)
from sports_intelligence.domain.retrieval.trajectory_window import (
    DEFAULT_TRAJECTORY_WINDOW,
    TrajectoryWindowPolicy,
)
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

TRAJECTORY_PROFILE_FINGERPRINT_ALGORITHM: Final[str] = "trajectory-profile-sha256-v1"

#: O perfil de trajetória da V1. O nome carrega as três decisões: eixos
#: robustos, múltiplos horizontes, deslocamento.
ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1: Final[str] = (
    "ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1"
)


@final
class TrajectoryRepresentationMethod(StrEnum):
    """Como o movimento vira número. Catálogo FECHADO.

    UM MEMBRO SÓ, e os que faltam são a decisão. `VELOCITY` (`Δ/h`) e
    `ACCELERATION` (`Δ²`) não estão aqui: a primeira muda a unidade — de «IQR»
    para «IQR por minuto» — e tornaria a penalidade `p = 1` do PR-06.2
    incomparável com a do estado; a segunda exige três instantes por célula e
    uma decisão sobre o que fazer quando um deles falta.

    `LEVEL_CONCATENATION` também não está: ela é a representação que este PR
    existe para NÃO usar (§45).
    """

    #: `Δ_{h,i} = x_i(t) - x_i(t-h)`, em unidades de IQR da competição.
    ABSOLUTE_DISPLACEMENT = DISPLACEMENT_REPRESENTATION_V1


@final
@dataclass(frozen=True, slots=True)
class TrajectoryRetrievalProfile:
    """A REGRA da trajetória: quais eixos, quais horizontes, qual movimento.

    ELA COMPÕE O PERFIL DE ESTADO em vez de o substituir. `base` é o perfil do
    PR-06.2, e é dele que saem os eixos — este contrato acrescenta a dimensão
    temporal, e nada mais.
    """

    name: str = ROBUST_MULTI_HORIZON_DISPLACEMENT_TRAJECTORY_V1
    version: int = 1
    base: RetrievalFeatureProfile = AVAILABILITY_AWARE_RETRIEVAL_PROFILE
    window: TrajectoryWindowPolicy = DEFAULT_TRAJECTORY_WINDOW
    representation: TrajectoryRepresentationMethod = (
        TrajectoryRepresentationMethod.ABSOLUTE_DISPLACEMENT
    )

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("perfil de trajetória sem nome")
        if self.version < 1:
            raise ValidationError(f"versão de perfil inválida: {self.version}")
        if self.base.missing_policy is not MissingPolicy.AVAILABILITY_AWARE:
            raise ValidationError(
                f"perfil base com política de ausência {self.base.missing_policy.value}: "
                "a trajetória herda os eixos do perfil CIENTE DE DISPONIBILIDADE, e "
                "usar o de caso completo mudaria o espaço junto com a pergunta — a "
                "comparação entre estado e trajetória deixaria de medir só a pergunta",
                context={"missing_policy": self.base.missing_policy.value},
            )
        if self.base.weight_policy is not WeightPolicy.EQUAL:
            raise ValidationError(
                "perfil base com ponderação: toda célula de trajetória vale 1 na V1"
            )

    # ------------------------------------------------------------ leitura --

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def horizons(self) -> tuple[int, ...]:
        return self.window.horizons

    @property
    def is_diagnostic(self) -> bool:
        """Ela NÃO é a similaridade final, e nem metade dela.

        A TRAJETÓRIA É UM SINAL INDEPENDENTE (§4, §258). Combiná-la com o
        estado num número só é uma decisão de ponderação que ainda não tem com
        o que ser calibrada.
        """
        return True

    def resolve(self, base: ResolvedRetrievalProfile) -> ResolvedTrajectoryProfile:
        """Os eixos e os horizontes desta competição.

        ELE RECEBE O PERFIL JÁ RESOLVIDO, e é a garantia do §35: não há
        segunda seleção de eixos, logo não há como divergir da primeira.
        """
        if base.base.fingerprint != self.base.fingerprint:
            raise ValidationError(
                "o perfil resolvido veio de outra regra de seleção: os eixos da "
                "trajetória são os MESMOS do estado, e resolver sob regras diferentes "
                "quebraria a única coisa que torna os dois comparáveis",
                context={
                    "expected": self.base.fingerprint,
                    "found": base.base.fingerprint,
                },
            )
        return ResolvedTrajectoryProfile(profile=self, base=base)

    # -------------------------------------------------------------- forma --

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_PROFILE_FINGERPRINT_ALGORITHM,
            "base_profile": self.base.as_canonical(),
            "horizon_order": list(self.window.horizons),
            "name": self.name,
            "representation": self.representation.value,
            "version": self.version,
            "window_fingerprint": self.window.fingerprint,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        return f"{self.identity} [{self.fingerprint[:12]}]"


@final
@dataclass(frozen=True, slots=True)
class ResolvedTrajectoryProfile:
    """Os eixos e horizontes de UMA competição, com identidade própria."""

    profile: TrajectoryRetrievalProfile
    base: ResolvedRetrievalProfile

    # ------------------------------------------------------------ leitura --

    @property
    def feature_keys(self) -> tuple[str, ...]:
        return self.base.feature_keys

    @property
    def horizons(self) -> tuple[int, ...]:
        return self.profile.horizons

    @property
    def axis_count(self) -> int:
        """`m`."""
        return self.base.axis_count

    @property
    def horizon_count(self) -> int:
        """`|H|`."""
        return len(self.horizons)

    @property
    def cell_count(self) -> int:
        """`n = |H| · m` — o denominador FIXO da dissimilaridade."""
        return self.horizon_count * self.axis_count

    @property
    def competition(self) -> str:
        return self.base.competition

    @property
    def is_empty(self) -> bool:
        return self.base.is_empty

    def cell_labels(self) -> tuple[str, ...]:
        """`("1m/xg_home_10m", …)` — para a evidência e o relatório."""
        return tuple(f"{h}m/{chave}" for h in self.horizons for chave in self.feature_keys)

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": TRAJECTORY_PROFILE_FINGERPRINT_ALGORITHM,
            "base_resolved_fingerprint": self.base.fingerprint,
            "cell_count": self.cell_count,
            "competition": self.base.competition,
            "feature_order": list(self.feature_keys),
            "horizon_order": list(self.horizons),
            "profile": self.profile.as_canonical(),
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def diagnostics(self) -> Mapping[str, object]:
        return {
            "axis_count": self.axis_count,
            "cell_count": self.cell_count,
            "competition": self.competition,
            "horizon_count": self.horizon_count,
            **self.base.diagnostics(),
        }

    def __str__(self) -> str:
        return (
            f"{self.profile.name}/{self.competition}: {self.axis_count} eixos x "
            f"{self.horizon_count} horizontes = {self.cell_count} células "
            f"[{self.fingerprint[:12]}]"
        )


#: O perfil de produção da V1.
DEFAULT_TRAJECTORY_PROFILE: Final[TrajectoryRetrievalProfile] = TrajectoryRetrievalProfile()


def trajectory_profile_summary(profile: ResolvedTrajectoryProfile) -> Sequence[str]:
    """As linhas do resumo legível — para a CLI e para o relatório."""
    return [
        f"{profile.profile.identity} / {profile.competition}",
        f"eixos       {profile.axis_count}",
        f"horizontes  {list(profile.horizons)}",
        f"células     {profile.cell_count}",
        f"impressão   {profile.fingerprint[:16]}",
    ]
