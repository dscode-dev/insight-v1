"""O detalhe de cada evento — tipado, e não um dicionário livre.

POR QUE NÃO `attributes: dict[str, Any]`. Um dicionário livre parece
flexível e custa caro:

- o nome da chave vira convenção oral: `body_part`, `bodyPart`, `foot`;
- nenhum type checker pega o consumidor que lê a chave errada;
- o valor ausente e o valor zero ficam indistinguíveis;
- e o schema real passa a ser "o que os provedores mandaram até hoje".

Tipar o detalhe move essas falhas do runtime para o checker.

MODELADO SÓ O QUE OS PRÓXIMOS ENGINES PRECISAM. Futebol profissional tem
centenas de atributos por evento; reproduzi-los agora seria inventar campos
que ninguém preenche. Estes são os que sustentam finalização, passe,
disciplina, substituição e goleiro — e crescem no PR que precisar.

XG É DADO OBSERVADO, NUNCA CALCULADO AQUI. Quando uma fonte fornece, ele
entra como observação com procedência. O motor NÃO calcula xG neste PR, e
quando calcular será uma feature derivada com versão própria — as duas coisas
não se misturam, porque comparar um xG de fonte com um xG nosso mediria a
diferença entre modelos e não entre partidas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import final

from sports_intelligence.domain.shared.feature_value import FeatureValue
from sports_intelligence.domain.shared.identity import PlayerId


class BodyPart(StrEnum):
    RIGHT_FOOT = "RIGHT_FOOT"
    LEFT_FOOT = "LEFT_FOOT"
    HEAD = "HEAD"
    OTHER = "OTHER"


class ShotOutcome(StrEnum):
    GOAL = "GOAL"
    SAVED = "SAVED"
    OFF_TARGET = "OFF_TARGET"
    BLOCKED = "BLOCKED"
    POST = "POST"


@final
@dataclass(frozen=True, slots=True)
class ShotDetail:
    """Uma finalização.

    `xg` é `FeatureValue` e não `float | None` de propósito: xG ausente NÃO é
    xG zero (Constituição §4). Zero significaria "chance nula", que é uma
    afirmação sobre algo não medido — e ela entraria em qualquer média.
    """

    outcome: ShotOutcome
    body_part: BodyPart | None = None
    #: xG FORNECIDO PELA FONTE. Nunca calculado aqui.
    xg: FeatureValue | None = None

    def __post_init__(self) -> None:
        if self.xg is not None and self.xg.is_available:
            valor = self.xg.require("ShotDetail.xg")
            if not 0.0 <= valor <= 1.0:
                raise ValueError(f"xG={valor} fora de [0,1]: é uma probabilidade")

    @property
    def is_goal(self) -> bool:
        return self.outcome is ShotOutcome.GOAL

    @property
    def on_target(self) -> bool:
        """No alvo: entrou ou o goleiro defendeu.

        Trave NÃO conta, e a escolha merece nota: a convenção estatística
        padrão exclui bola na trave de "chutes no alvo", porque ela não
        exigiu defesa. Bloqueio também não — quem bloqueou foi um zagueiro.
        """
        return self.outcome in (ShotOutcome.GOAL, ShotOutcome.SAVED)


class PassOutcome(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    OUT = "OUT"
    OFFSIDE = "OFFSIDE"


@final
@dataclass(frozen=True, slots=True)
class PassDetail:
    """Um passe. `recipient_id` só existe quando chegou a alguém."""

    outcome: PassOutcome
    recipient_id: PlayerId | None = None
    body_part: BodyPart | None = None

    def __post_init__(self) -> None:
        # Um passe incompleto com destinatário é contraditório: ou chegou, ou
        # não chegou. Aceitar os dois faria "passes recebidos" contar passes
        # que não chegaram.
        if self.outcome is not PassOutcome.COMPLETE and self.recipient_id is not None:
            raise ValueError(
                f"passe {self.outcome} com destinatário: só passe completo tem quem recebeu"
            )


class CardType(StrEnum):
    """Amarelo, segundo amarelo e vermelho direto.

    SEGUNDO AMARELO É SEPARADO DE VERMELHO, e isso não é preciosismo. As duas
    expulsões descrevem situações diferentes: o segundo amarelo costuma vir de
    acúmulo de faltas táticas ao longo do jogo; o vermelho direto vem de um
    lance grave e isolado. Para descrever o que estava acontecendo na partida,
    a distinção é o dado.
    """

    YELLOW = "YELLOW"
    SECOND_YELLOW = "SECOND_YELLOW"
    RED = "RED"

    @property
    def is_dismissal(self) -> bool:
        """Se o jogador saiu de campo."""
        return self in (CardType.SECOND_YELLOW, CardType.RED)


@final
@dataclass(frozen=True, slots=True)
class CardDetail:
    card_type: CardType
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason vazio: omita em vez de mandar vazio")


@final
@dataclass(frozen=True, slots=True)
class SubstitutionDetail:
    """Quem saiu e quem entrou.

    Os dois no mesmo detalhe porque uma substituição é UMA transição, não dois
    eventos. Modelá-la como saída e entrada separadas permitiria um par
    desemparelhado — um jogador que sai e ninguém entra.
    """

    player_out: PlayerId
    player_in: PlayerId

    def __post_init__(self) -> None:
        if self.player_out == self.player_in:
            raise ValueError(
                f"jogador {self.player_out} substituindo a si mesmo — "
                "quase sempre resolução de identidade que fundiu dois jogadores"
            )


class GoalkeeperActionType(StrEnum):
    SAVE = "SAVE"
    CLAIM = "CLAIM"
    PUNCH = "PUNCH"
    SWEEP = "SWEEP"
    DISTRIBUTION = "DISTRIBUTION"


class GoalkeeperOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@final
@dataclass(frozen=True, slots=True)
class GoalkeeperDetail:
    action_type: GoalkeeperActionType
    outcome: GoalkeeperOutcome


class DuelOutcome(StrEnum):
    WON = "WON"
    LOST = "LOST"
    NEUTRAL = "NEUTRAL"


@final
@dataclass(frozen=True, slots=True)
class DuelDetail:
    """Uma disputa. `opponent_id` opcional porque nem toda fonte diz contra
    quem foi — e inventá-lo seria pior que não ter."""

    outcome: DuelOutcome
    opponent_id: PlayerId | None = None


#: A união dos detalhes tipados. `None` é legítimo: eventos estruturais
#: (apito inicial) e interrupções não têm detalhe próprio, e um detalhe vazio
#: obrigatório seria ruído.
EventDetail = (
    ShotDetail | PassDetail | CardDetail | SubstitutionDetail | GoalkeeperDetail | DuelDetail
)
