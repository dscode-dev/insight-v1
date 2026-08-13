"""Posição e função: dois conceitos que parecem um.

**Position** é estrutural — onde o jogador se posiciona no desenho da equipe.
É o que a escalação declara e o que uma formação 4-3-3 descreve.

**TacticalRole** é contextual — o que ele faz naquele desenho. Dois volantes
na mesma posição `DM` podem ser um `HOLDING_MIDFIELDER` que fica e um
`BOX_TO_BOX` que chega na área, e a diferença muda completamente como a
partida se comporta.

TRATÁ-LOS COMO SINÔNIMOS APAGA O SEGUNDO. E é o segundo que descreve estilo —
exatamente o que uma comparação entre partidas históricas precisa distinguir.

A TAXONOMIA DE FUNÇÃO É PEQUENA DE PROPÓSITO. Cinquenta funções inventadas
agora seriam cinquenta rótulos que nenhuma fonte preenche e que ninguém sabe
distinguir. Estas cinco são as que aparecem em qualquer descrição tática, e o
`extra` guarda o que a fonte disse quando não couber — sem virar dicionário
livre.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final


class Position(StrEnum):
    """Onde o jogador se posiciona. Estrutural, não contextual."""

    GK = "GK"
    CB = "CB"
    LB = "LB"
    RB = "RB"
    LWB = "LWB"
    RWB = "RWB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    LW = "LW"
    RW = "RW"
    ST = "ST"

    @property
    def line(self) -> PositionLine:
        return _LINHAS[self]

    @property
    def is_goalkeeper(self) -> bool:
        return self is Position.GK


class PositionLine(StrEnum):
    """A linha do campo. Agrupa posições para descrição estrutural.

    Existe porque perguntas como "quantos defensores" precisam de resposta
    sem que cada consumidor invente o próprio agrupamento — três agrupamentos
    divergem na primeira vez que alguém decide se `LWB` é defesa ou meio.
    """

    GOALKEEPER = "GOALKEEPER"
    DEFENCE = "DEFENCE"
    MIDFIELD = "MIDFIELD"
    ATTACK = "ATTACK"


#: Ala é DEFESA aqui, e a escolha merece nota: `LWB`/`RWB` jogam adiantados,
#: mas ocupam a linha defensiva quando a equipe não tem a bola — que é o
#: momento em que a contagem de defensores importa.
_LINHAS: Final[dict[Position, PositionLine]] = {
    Position.GK: PositionLine.GOALKEEPER,
    Position.CB: PositionLine.DEFENCE,
    Position.LB: PositionLine.DEFENCE,
    Position.RB: PositionLine.DEFENCE,
    Position.LWB: PositionLine.DEFENCE,
    Position.RWB: PositionLine.DEFENCE,
    Position.DM: PositionLine.MIDFIELD,
    Position.CM: PositionLine.MIDFIELD,
    Position.AM: PositionLine.MIDFIELD,
    Position.LW: PositionLine.ATTACK,
    Position.RW: PositionLine.ATTACK,
    Position.ST: PositionLine.ATTACK,
}


class RoleCode(StrEnum):
    """As funções que a V1 reconhece. Pequena e fechada, por ora."""

    HOLDING_MIDFIELDER = "HOLDING_MIDFIELDER"
    BOX_TO_BOX = "BOX_TO_BOX"
    WINGER = "WINGER"
    INSIDE_FORWARD = "INSIDE_FORWARD"
    TARGET_FORWARD = "TARGET_FORWARD"


@final
@dataclass(frozen=True, slots=True)
class TacticalRole:
    """O que o jogador faz, não onde ele fica.

    EXTENSÍVEL E VALIDADO. `RoleCode` cobre o conhecido; `extra` guarda o que
    uma fonte descreveu e ainda não virou código — como texto normalizado, e
    não como dicionário livre. Quando um `extra` aparecer com frequência, ele
    vira `RoleCode` num diff, com a decisão registrada.
    """

    code: RoleCode | None = None
    extra: str | None = None

    def __post_init__(self) -> None:
        if (self.code is None) == (self.extra is None):
            raise ValueError(
                "TacticalRole é um código conhecido OU um extra descrito, nunca ambos "
                "nem nenhum — sem isso a função vira um campo que às vezes está lá"
            )
        if self.extra is not None:
            texto = self.extra.strip().upper().replace(" ", "_").replace("-", "_")
            if not texto:
                raise ValueError("extra vazio")
            if not texto.replace("_", "").isalnum():
                raise ValueError(f"extra {self.extra!r} inválido: letras, dígitos e underscore")
            object.__setattr__(self, "extra", texto)

    @classmethod
    def known(cls, code: RoleCode) -> TacticalRole:
        return cls(code=code)

    @classmethod
    def described(cls, text: str) -> TacticalRole:
        return cls(extra=text)

    @property
    def is_known(self) -> bool:
        return self.code is not None

    def __str__(self) -> str:
        return str(self.code) if self.code is not None else f"~{self.extra}"
