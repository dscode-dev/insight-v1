"""Onde no campo — e por que o referencial precisa ser declarado.

O PROBLEMA. Times trocam de lado no intervalo. Provedores discordam sobre a
origem: uns põem (0,0) no canto inferior esquerdo, outros no centro, outros
invertem o eixo Y. Um chute a 5 metros do gol vira um chute do próprio campo
dependendo de quem descreveu — e a coordenada continua sendo um par de
números perfeitamente válido.

Comparar coordenadas de referenciais diferentes é somar metros com jardas sem
que nada falhe.

A ESCOLHA: `ATTACKING` COMO REFERENCIAL CANÔNICO.

    x = 0.0   o próprio gol de quem executa a ação
    x = 1.0   o gol adversário
    y = 0.0   uma lateral
    y = 1.0   a outra

Assim um chute perigoso é `x ≈ 0.95` SEMPRE — primeiro tempo, segundo tempo,
mandante, visitante. É o que torna duas partidas comparáveis sem que cada
consumidor precise saber para que lado cada time atacava.

`ABSOLUTE` existe para o que é do estádio e não do time: posição de câmera,
lado do banco. Ele é aceito, DECLARADO, e não se compara com `ATTACKING`.

NADA DE NUMPY para guardar dois floats. A stack o prevê para matemática de
verdade; usá-lo aqui seria peso sem ganho.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final


class CoordinateFrame(StrEnum):
    """O referencial de uma coordenada. Declarado, nunca suposto."""

    #: Normalizado pelo sentido de ataque de QUEM executa a ação.
    #: `x=1` é sempre o gol adversário. É o canônico do motor.
    ATTACKING = "ATTACKING"
    #: Fixo ao estádio. `x=0` é sempre o mesmo lado do campo,
    #: independentemente de quem ataca. Só para o que é do estádio.
    ABSOLUTE = "ABSOLUTE"


@final
@dataclass(frozen=True, slots=True)
class PitchCoordinate:
    """Um ponto no campo, normalizado em [0,1], com referencial declarado.

    NORMALIZADO E NÃO EM METROS porque as dimensões variam: 105 por 68 metros
    é o padrão e não é obrigatório. Comparar 30 metros do Maracanã com 30
    metros de um campo menor compara frações diferentes do campo.
    """

    x: float
    y: float
    frame: CoordinateFrame = CoordinateFrame.ATTACKING

    def __post_init__(self) -> None:
        for nome, valor in (("x", self.x), ("y", self.y)):
            if not 0.0 <= valor <= 1.0:
                raise ValueError(
                    f"{nome}={valor!r} fora de [0,1]: a coordenada é normalizada, "
                    "não está em metros"
                )
        object.__setattr__(self, "x", float(self.x))
        object.__setattr__(self, "y", float(self.y))

    def assert_comparable(self, other: PitchCoordinate) -> None:
        """Recusa comparar coordenadas de referenciais diferentes.

        Sem esta guarda, a distância entre um ponto `ATTACKING` e um
        `ABSOLUTE` é calculável e sem sentido — e o número não denuncia nada.
        """
        if self.frame is not other.frame:
            raise ValueError(
                f"referenciais diferentes: {self.frame} e {other.frame}. "
                "Converta explicitamente antes de comparar."
            )

    def flip(self) -> Self:
        """O mesmo ponto visto do lado oposto.

        A conversão entre os sentidos de ataque das duas equipes: espelha nos
        dois eixos, porque virar o campo inverte também a lateral.
        """
        return type(self)(x=1.0 - self.x, y=1.0 - self.y, frame=self.frame)

    def distance_to(self, other: PitchCoordinate) -> float:
        """Distância euclidiana em unidades normalizadas.

        NÃO É EM METROS, e não deve ser convertida sem as dimensões reais do
        campo — que o motor não tem. Serve para comparar, não para medir.
        """
        self.assert_comparable(other)
        dx = self.x - other.x
        dy = self.y - other.y
        return float((dx * dx + dy * dy) ** 0.5)

    @property
    def distance_to_opponent_goal(self) -> float:
        """Quão perto do gol adversário. Só faz sentido em `ATTACKING`.

        Em `ABSOLUTE` não existe "gol adversário" — o referencial não sabe
        quem ataca para onde.
        """
        if self.frame is not CoordinateFrame.ATTACKING:
            raise ValueError(
                f"distância ao gol adversário exige o referencial ATTACKING, "
                f"esta coordenada é {self.frame}"
            )
        return self.distance_to(OPPONENT_GOAL)

    def __str__(self) -> str:
        return f"({self.x:.3f},{self.y:.3f})@{self.frame}"


#: O centro do gol adversário no referencial de ataque. Constante nomeada
#: porque `(1.0, 0.5)` espalhado pelo código é um número mágico repetido.
OPPONENT_GOAL: PitchCoordinate = PitchCoordinate(x=1.0, y=0.5)

#: O centro do próprio gol.
OWN_GOAL: PitchCoordinate = PitchCoordinate(x=0.0, y=0.5)

#: O meio do campo.
PITCH_CENTRE: PitchCoordinate = PitchCoordinate(x=0.5, y=0.5)
