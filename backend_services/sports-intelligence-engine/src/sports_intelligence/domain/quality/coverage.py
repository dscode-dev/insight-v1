"""Cobertura — QUANTAS famílias de dado existem. Não é qualidade.

A CONFUSÃO QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§4). Um dataset assim:

    placar    100%        escalação   0%
    chutes    100%        eventos     0%
    cartões   100%        odds        0%

não é um dataset ruim. É um dataset de **alta qualidade e baixa riqueza** — e
tratá-lo como ruim faria o motor rejeitar exatamente as fontes públicas de
futebol, que são confiáveis e enxutas.

O inverso também é verdade e é mais perigoso: uma fonte com escalação, eventos
e coordenadas, e com identidades mal resolvidas, tem **alta riqueza e baixa
qualidade**. Um score único as classificaria parecido.

Por isso são dois modelos, dois campos e dois relatórios. `QualityVector`
responde «posso confiar no que está aqui?»; `CoverageReport` responde «o que
está aqui?».

COBERTURA NÃO BLOQUEIA POR PADRÃO (§85). `eventos = 0%` reduz o que se pode
construir sobre o corpus e não invalida um histórico de nível de partida. A
política de build pode exigir níveis mínimos para builds especializados — e
isso é decisão dela, declarada, não um efeito colateral do avaliador.

O DENOMINADOR HONESTO É O ASSUNTO DIFÍCIL (§13). `76% de escalações` só
significa alguma coisa se «100%» for definível. Quando não for — uma fonte que
simplesmente não publica escalação —, o certo é dizer `INDISPONÍVEL`, e não
inventar um denominador para produzir um zero que parece uma falha.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.shared.errors import ValidationError


class CoverageFamily(StrEnum):
    """As famílias de dado que um corpus histórico pode ter.

    `TRACKING` EXISTE E É SEMPRE `NOT_DECLARED` NA V1 (§20). Ela está aqui
    para que a ausência seja NOMEADA em vez de esquecida: um relatório que não
    menciona tracking não distingue «não temos» de «ninguém pensou nisso». O
    que NÃO existe é schema de tracking — inventá-lo para preencher a
    categoria seria criar dívida para decorar um relatório.
    """

    MATCH = "MATCH"
    LINEUP = "LINEUP"
    EVENT = "EVENT"
    PLAYER = "PLAYER"
    ODDS = "ODDS"
    SPATIAL = "SPATIAL"
    TRACKING = "TRACKING"


#: Ordem canônica, pelo mesmo motivo da ordem das dimensões: ela entra na
#: impressão do manifesto.
FAMILY_ORDER: Final[tuple[CoverageFamily, ...]] = (
    CoverageFamily.MATCH,
    CoverageFamily.LINEUP,
    CoverageFamily.EVENT,
    CoverageFamily.PLAYER,
    CoverageFamily.ODDS,
    CoverageFamily.SPATIAL,
    CoverageFamily.TRACKING,
)


class CoverageState(StrEnum):
    """O que se pode afirmar sobre uma família.

    TRÊS ESTADOS E NÃO UM NÚMERO, porque «0%» é ambíguo e a ambiguidade é
    cara: ela confunde «a fonte declara eventos e não trouxe nenhum» — que é
    defeito — com «a fonte não trabalha com eventos» — que é o normal.
    """

    #: Há denominador honesto: sabemos quantos deveriam existir.
    MEASURED = "MEASURED"
    #: Há contagem e não há denominador. Reporta-se a disponibilidade nua.
    AVAILABILITY_ONLY = "AVAILABILITY_ONLY"
    #: A fonte não trabalha com esta família. NÃO é uma falha.
    NOT_DECLARED = "NOT_DECLARED"


@final
@dataclass(frozen=True, slots=True)
class FamilyCoverage:
    """A cobertura de UMA família.

    `expected_count` É `None` QUANDO NÃO HÁ DENOMINADOR HONESTO, e o tipo
    obriga quem lê a lidar com isso. Um `int` com zero teria permitido
    `available / expected` explodir ou, pior, produzir silenciosamente um
    `0.0` que pareceria uma medição.
    """

    family: CoverageFamily
    state: CoverageState
    available_count: int = 0
    expected_count: int | None = None

    def __post_init__(self) -> None:
        if self.available_count < 0:
            raise ValidationError(
                f"{self.family}: contagem negativa ({self.available_count})"
            )
        if self.expected_count is not None and self.expected_count < 0:
            raise ValidationError(f"{self.family}: esperado negativo")
        if self.state is CoverageState.MEASURED and self.expected_count is None:
            raise ValidationError(
                f"{self.family} declarada MEASURED sem denominador — «medido» sem "
                "esperado é disponibilidade com outro nome, e o nome errado faz o "
                "relatório afirmar mais do que sabe"
            )
        if self.state is CoverageState.NOT_DECLARED and self.available_count:
            raise ValidationError(
                f"{self.family} declarada NOT_DECLARED com {self.available_count} "
                "itens presentes: a fonte trouxe o que disse não ter"
            )

    @classmethod
    def measured(cls, family: CoverageFamily, *, available: int, expected: int) -> Self:
        if available > expected:
            raise ValidationError(
                f"{family}: {available} disponíveis de {expected} esperados — a "
                "cobertura passaria de 100%, o que significa que o denominador "
                "está errado"
            )
        return cls(
            family=family,
            state=CoverageState.MEASURED,
            available_count=available,
            expected_count=expected,
        )

    @classmethod
    def availability(cls, family: CoverageFamily, *, available: int) -> Self:
        return cls(
            family=family,
            state=CoverageState.AVAILABILITY_ONLY,
            available_count=available,
        )

    @classmethod
    def not_declared(cls, family: CoverageFamily) -> Self:
        return cls(family=family, state=CoverageState.NOT_DECLARED)

    @property
    def ratio(self) -> float | None:
        """A fração, ou `None` quando não há denominador.

        `None` E NÃO `0.0`: a diferença entre «medimos e deu zero» e «não dá
        para medir» é a diferença entre um defeito e uma característica da
        fonte, e um `0.0` apagaria as duas na mesma linha de relatório.
        """
        if self.state is not CoverageState.MEASURED or not self.expected_count:
            return None
        return self.available_count / self.expected_count

    def as_canonical(self) -> dict[str, object]:
        return {
            "available": self.available_count,
            "expected": self.expected_count,
            "family": self.family.value,
            "ratio": None if self.ratio is None else round(self.ratio, 6),
            "state": self.state.value,
        }

    def __str__(self) -> str:
        if self.ratio is not None:
            return f"{self.family} {self.ratio:.0%} ({self.available_count}/{self.expected_count})"
        if self.state is CoverageState.NOT_DECLARED:
            return f"{self.family} não declarada"
        return f"{self.family} {self.available_count} disponível(is)"


@final
@dataclass(frozen=True, slots=True)
class CoverageReport:
    """A cobertura de um escopo — uma partida, uma temporada, um corpus.

    O MESMO TIPO SERVE AOS TRÊS NÍVEIS de propósito. Um tipo por nível
    produziria três classes idênticas cuja única diferença seria o nome, e a
    agregação entre elas exigiria conversão — que é onde as contagens se
    perdem.
    """

    families: tuple[FamilyCoverage, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        nomes = [f.family for f in self.families]
        if len(set(nomes)) != len(nomes):
            repetidas = sorted({n.value for n in nomes if nomes.count(n) > 1})
            raise ValidationError(
                f"família de cobertura duas vezes no mesmo relatório: {repetidas}"
            )

    @classmethod
    def of(cls, *families: FamilyCoverage) -> Self:
        """Constrói em ORDEM CANÔNICA, independente da ordem de chamada."""
        por_familia = {f.family: f for f in families}
        return cls(
            families=tuple(por_familia[f] for f in FAMILY_ORDER if f in por_familia)
        )

    def of_family(self, family: CoverageFamily) -> FamilyCoverage | None:
        return next((f for f in self.families if f.family is family), None)

    def ratio_of(self, family: CoverageFamily) -> float | None:
        cobertura = self.of_family(family)
        return cobertura.ratio if cobertura else None

    @property
    def declared_families(self) -> tuple[CoverageFamily, ...]:
        """As famílias que a fonte de fato trabalha — as que dá para exigir."""
        return tuple(
            f.family for f in self.families if f.state is not CoverageState.NOT_DECLARED
        )

    def merged_with(self, other: CoverageReport) -> CoverageReport:
        """Soma cobertura de dois escopos — de partida para temporada, por exemplo.

        SOMAR CONTAGENS E NÃO PROMEDIAR FRAÇÕES. A média de `100%` sobre uma
        partida e `0%` sobre outras noventa e nove daria `50%` se ponderada
        por partida em vez de por item — e o relatório afirmaria metade da
        cobertura que existe.

        DUAS FAMÍLIAS SÓ SOMAM SE AS DUAS TIVEREM DENOMINADOR. Uma medida mais
        uma disponibilidade vira disponibilidade: o denominador que falta de um
        lado não é zero, é desconhecido.
        """
        juntas: list[FamilyCoverage] = []
        for familia in FAMILY_ORDER:
            aqui, la = self.of_family(familia), other.of_family(familia)
            if aqui is None or la is None:
                escolhida = aqui or la
                if escolhida is not None:
                    juntas.append(escolhida)
                continue
            if aqui.state is CoverageState.NOT_DECLARED:
                juntas.append(la)
                continue
            if la.state is CoverageState.NOT_DECLARED:
                juntas.append(aqui)
                continue
            disponiveis = aqui.available_count + la.available_count
            if aqui.expected_count is not None and la.expected_count is not None:
                juntas.append(
                    FamilyCoverage.measured(
                        familia,
                        available=disponiveis,
                        expected=aqui.expected_count + la.expected_count,
                    )
                )
            else:
                juntas.append(FamilyCoverage.availability(familia, available=disponiveis))
        return CoverageReport.of(*juntas)

    def as_canonical(self) -> list[dict[str, object]]:
        return [f.as_canonical() for f in self.families]

    def __str__(self) -> str:
        return " · ".join(str(f) for f in self.families) or "sem cobertura declarada"
