"""Quais eixos a projeção guarda, e em que ordem.

ELE NÃO É UMA REPRESENTAÇÃO — é uma LISTA ORDENADA. O que a projeção persiste
são os `float64` do dataset normalizado; o que este objeto declara é sobre
QUAIS eixos, e em que ordem eles entram no `bytea`.

A ORDEM É A DO PLANO, e ela é a identidade posicional do payload: decodificar
com outra ordem devolveria números certos atribuídos a eixos errados, sem erro
nenhum. Por isso ela entra na impressão.

OS EIXOS SÃO OS 29 CANÔNICOS, E NÃO O PERFIL RESOLVIDO. O perfil varia por
competição — quinze eixos na Premier League do corpus —, e a projeção precisa
de um formato só. Um eixo que a competição não ajustou entra com máscara zero,
que é exatamente o que ele é ali: indisponível. O recorte para o perfil
acontece na LEITURA, e é o que faz a representação reconstruída ser idêntica à
que o oráculo montaria do Parquet.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError

AXIS_SPEC_FINGERPRINT_ALGORITHM: Final[str] = "projection-axis-spec-sha256-v1"

CANONICAL_ROBUST_AXES_V1: Final[str] = "CANONICAL_ROBUST_AXES_V1"


@final
@dataclass(frozen=True, slots=True)
class ProjectionAxisSpec:
    """Os eixos canônicos de uma projeção, em ordem, com identidade própria."""

    name: str
    version: int
    axis_keys: tuple[str, ...]
    horizons: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.axis_keys:
            raise ValidationError("uma projeção sem eixos não guarda representação nenhuma")
        if len(set(self.axis_keys)) != len(self.axis_keys):
            raise ValidationError("eixo repetido na projeção: a posição no payload ficaria ambígua")

    @property
    def axis_count(self) -> int:
        return len(self.axis_keys)

    @property
    def cell_count(self) -> int:
        """`R` no estado, `|H| . R` na trajetória."""
        return max(len(self.horizons), 1) * self.axis_count

    @property
    def identity(self) -> str:
        return f"{self.name}@{self.version}"

    def as_canonical(self) -> dict[str, object]:
        return {
            "algorithm": AXIS_SPEC_FINGERPRINT_ALGORITHM,
            "axis_keys": list(self.axis_keys),
            "horizons": list(self.horizons),
            "name": self.name,
            "version": self.version,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(self.as_canonical())).hexdigest()

    def __str__(self) -> str:
        horizontes = f" x {len(self.horizons)} horizontes" if self.horizons else ""
        return (
            f"{self.identity} · {self.axis_count} eixos{horizontes} "
            f"= {self.cell_count} células [{self.fingerprint[:12]}]"
        )


def state_axis_spec(axis_keys: Sequence[str]) -> ProjectionAxisSpec:
    return ProjectionAxisSpec(name=CANONICAL_ROBUST_AXES_V1, version=1, axis_keys=tuple(axis_keys))


def trajectory_axis_spec(
    axis_keys: Sequence[str], *, horizons: Sequence[int] = (1, 3, 5)
) -> ProjectionAxisSpec:
    if not horizons:
        raise ValidationError("uma projeção de trajetória sem horizontes")
    return ProjectionAxisSpec(
        name=CANONICAL_ROBUST_AXES_V1,
        version=1,
        axis_keys=tuple(axis_keys),
        horizons=tuple(horizons),
    )
