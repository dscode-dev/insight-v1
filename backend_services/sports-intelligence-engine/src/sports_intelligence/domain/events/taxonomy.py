"""A taxonomia de eventos do Insight — nossa, não de nenhum provedor.

POR QUE NÃO ADOTAR A DE UM PROVEDOR. A taxonomia da StatsBomb tem dezenas de
tipos e reflete o método de coleta dela; a da Opta reflete o dela. Adotar uma
faz duas coisas ruins: amarra o motor ao vocabulário de um fornecedor, e
obriga o segundo fornecedor a ser traduzido para o primeiro — o que é pior
que traduzir os dois para um vocabulário próprio.

Esta lista é o que o motor precisa saber para descrever uma partida. Um tipo
que nenhum engine vai consumir é um tipo que ninguém preenche direito.

FECHADA NA V1, pelo mesmo motivo do catálogo de competições: um tipo por
string livre vira `"shot"`, `"Shot"` e `"SHOT"` na primeira semana.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class EventType(StrEnum):
    """Os eventos canônicos da V1."""

    # -- estrutura da partida --
    MATCH_START = "MATCH_START"
    PERIOD_START = "PERIOD_START"
    PERIOD_END = "PERIOD_END"
    MATCH_END = "MATCH_END"

    # -- posse --
    PASS = "PASS"
    CARRY = "CARRY"
    DRIBBLE = "DRIBBLE"

    # -- finalização --
    SHOT = "SHOT"
    #: Separado de SHOT de propósito: um gol contra não tem chute do
    #: executante, e um pênalti convertido tem um chute que é outro evento.
    GOAL = "GOAL"

    # -- defesa e disputa --
    PRESSURE = "PRESSURE"
    RECOVERY = "RECOVERY"
    INTERCEPTION = "INTERCEPTION"
    TACKLE = "TACKLE"
    DUEL = "DUEL"
    BLOCK = "BLOCK"
    CLEARANCE = "CLEARANCE"

    # -- infração --
    FOUL = "FOUL"
    OFFSIDE = "OFFSIDE"
    CARD = "CARD"

    # -- bola parada --
    CORNER = "CORNER"
    FREE_KICK = "FREE_KICK"
    THROW_IN = "THROW_IN"
    GOAL_KICK = "GOAL_KICK"

    # -- elenco --
    SUBSTITUTION = "SUBSTITUTION"

    # -- goleiro --
    GOALKEEPER_ACTION = "GOALKEEPER_ACTION"

    # -- interrupções --
    VAR = "VAR"
    INJURY_STOPPAGE = "INJURY_STOPPAGE"
    GENERAL_STOPPAGE = "GENERAL_STOPPAGE"

    @property
    def requires_team(self) -> bool:
        """Se o evento pertence necessariamente a um time.

        Os estruturais e as interrupções não pertencem a ninguém: o apito
        final não é do mandante. Exigir time neles obrigaria a inventar um.
        """
        return self not in _SEM_TIME

    @property
    def requires_player(self) -> bool:
        """Se o evento tem necessariamente um executante.

        Poucos exigem: um `DUEL` tem dois, uma `SUBSTITUTION` tem dois com
        papéis diferentes (e eles vão no detalhe tipado), e `PRESSURE` às
        vezes é coletiva. Só onde a ausência seria claramente um dado
        faltando.
        """
        return self in _COM_JOGADOR

    @property
    def is_structural(self) -> bool:
        """Marca o andamento da partida, não uma ação em campo."""
        return self in _ESTRUTURAIS

    @property
    def is_set_piece(self) -> bool:
        return self in _BOLA_PARADA

    @property
    def is_stoppage(self) -> bool:
        return self in _INTERRUPCOES


_SEM_TIME: Final = frozenset(
    {
        EventType.MATCH_START,
        EventType.PERIOD_START,
        EventType.PERIOD_END,
        EventType.MATCH_END,
        EventType.VAR,
        EventType.GENERAL_STOPPAGE,
    }
)

_COM_JOGADOR: Final = frozenset(
    {
        EventType.PASS,
        EventType.CARRY,
        EventType.DRIBBLE,
        EventType.SHOT,
        EventType.CARD,
        EventType.GOALKEEPER_ACTION,
    }
)

_ESTRUTURAIS: Final = frozenset(
    {
        EventType.MATCH_START,
        EventType.PERIOD_START,
        EventType.PERIOD_END,
        EventType.MATCH_END,
    }
)

_BOLA_PARADA: Final = frozenset(
    {
        EventType.CORNER,
        EventType.FREE_KICK,
        EventType.THROW_IN,
        EventType.GOAL_KICK,
    }
)

_INTERRUPCOES: Final = frozenset(
    {
        EventType.VAR,
        EventType.INJURY_STOPPAGE,
        EventType.GENERAL_STOPPAGE,
    }
)
