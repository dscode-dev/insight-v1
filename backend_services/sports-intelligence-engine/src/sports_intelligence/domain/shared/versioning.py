"""Versões explícitas — porque comparar através delas é comparar coisa nenhuma.

O QUE ISTO PROTEGE. Um vetor produzido pelo espaço de features v3 e outro pelo
v4 têm dimensões diferentes, escalas diferentes, ou as duas. A distância entre
eles é um número perfeitamente calculável e completamente sem sentido. Nada
falha: as normas existem, o cosseno retorna, o vizinho aparece.

A mesma armadilha vale para engine: uma tendência gerada pela v2 comparada com
o baseline da v1 produz um diff que descreve a mudança de código, não a
mudança dos dados.

ENTÃO A VERSÃO VIAJA COM O ARTEFATO, e a comparação entre artefatos de versões
diferentes é RECUSADA, não convertida. `assert_comparable` é onde essa recusa
acontece, e ela existe para que a recusa seja uma linha em vez de uma
convenção que alguém esquece.

SEMÂNTICA REDUZIDA, DE PROPÓSITO. Só `major.minor`, sem patch e sem
pré-lançamento. Uma versão de espaço de features não tem "correção que não
muda nada": ou o espaço mudou — e aí os vetores precisam ser refeitos — ou não
mudou. Oferecer um patch convidaria alguém a mudar o espaço sem incrementar o
que importa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar, Self, final

_PADRAO = re.compile(r"^v(?P<major>\d+)\.(?P<minor>\d+)$")


@dataclass(frozen=True, slots=True, order=True)
class Version:
    """`v3.1`. Ordenável, comparável, e sem conversão implícita entre tipos."""

    KIND: ClassVar[str] = "version"

    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0:
            raise ValueError(f"versão negativa: v{self.major}.{self.minor}")

    @classmethod
    def parse(cls, raw: str) -> Self:
        casou = _PADRAO.match(raw.strip())
        if casou is None:
            raise ValueError(
                f"{raw!r} não é uma {cls.KIND} válida — o formato é vMAJOR.MINOR, por exemplo v1.0"
            )
        return cls(major=int(casou["major"]), minor=int(casou["minor"]))

    @property
    def is_compatible_family(self) -> int:
        """O major. Artefatos com majors diferentes não se comparam."""
        return self.major

    def assert_comparable(self, other: Self) -> None:
        """Recusa a comparação entre artefatos que não podem ser comparados.

        POR QUE IGUALDADE EXATA E NÃO SÓ O MAJOR. Um minor novo pode
        acrescentar uma dimensão — o major segue igual porque nada antigo
        quebrou — e um vetor com uma dimensão a mais já não vive no mesmo
        espaço do anterior. Para retrieval, a única igualdade que serve é a
        total.
        """
        if type(self) is not type(other):
            raise VersionMismatchError(
                f"tipos de versão diferentes: {type(self).__name__} e {type(other).__name__}"
            )
        if self != other:
            raise VersionMismatchError(
                f"{self.KIND} incompatível: {self} contra {other} — "
                "artefatos de versões diferentes não são comparáveis, e compará-los "
                "produz um número válido sobre coisas diferentes"
            )

    def next_major(self) -> Self:
        return type(self)(major=self.major + 1, minor=0)

    def next_minor(self) -> Self:
        return type(self)(major=self.major, minor=self.minor + 1)

    def __str__(self) -> str:
        return f"v{self.major}.{self.minor}"


@final
@dataclass(frozen=True, slots=True, order=True)
class DatasetVersion(Version):
    """A versão de um conjunto de dados construído. Incrementa quando o
    conteúdo muda, mesmo que o schema não mude."""

    KIND: ClassVar[str] = "versão de dataset"


@final
@dataclass(frozen=True, slots=True, order=True)
class FeatureSpaceVersion(Version):
    """Quais dimensões existem e como são escaladas.

    A MAIS SENSÍVEL DAS QUATRO. Mudá-la invalida todo vetor gravado: eles
    passam a descrever um espaço que não existe mais, e a similaridade entre
    um vetor velho e um novo é aritmética sobre eixos diferentes.
    """

    KIND: ClassVar[str] = "versão do espaço de features"


@final
@dataclass(frozen=True, slots=True, order=True)
class EngineVersion(Version):
    """A versão de um motor de inteligência. Duas saídas geradas por versões
    diferentes descrevem regras diferentes, não dados diferentes."""

    KIND: ClassVar[str] = "versão de engine"


@final
@dataclass(frozen=True, slots=True, order=True)
class NormalizerVersion(Version):
    """Como o dado bruto do provedor vira canônico. Muda quando o mapeamento
    muda — e aí o canônico precisa ser reconstruído a partir do bruto."""

    KIND: ClassVar[str] = "versão do normalizador"


class VersionMismatchError(Exception):
    """Tentativa de comparar artefatos de versões incompatíveis."""
