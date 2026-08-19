"""Que tipos de evento MUDAM o estado estrutural — e a garantia de que a lista
é completa.

O DEFEITO QUE ESTE MÓDULO EXISTE PARA IMPEDIR (§86, §87, §88). O reducer
precisa saber, para cada `EventType`, se ele altera placar, escalação ou
disciplina. A forma óbvia de escrever isso é um `if` por tipo, com um `else`
que não faz nada — e o `else` é a armadilha: no dia em que a taxonomia ganhar
`PENALTY_AWARDED`, ele cairá ali em silêncio, e o estado passará a ignorar um
fato que muda o jogo sem que nada denuncie.

Aqui a classificação é um MAPA FECHADO E EXAUSTIVO. Um tipo novo sem
classificação faz o módulo falhar ao ser importado — o teste de arquitetura
pega isso antes de qualquer estado ser construído.

    NO_STRUCTURAL_EFFECT   o evento existe na projeção efetiva e não move o
                           estado ESTRUTURAL. Um chute é um fato do jogo, e o
                           que ele produz — contagem, xG, ritmo — é feature,
                           não estado (§84)
    SCORE                  altera o placar
    SUBSTITUTION           altera quem está em campo
    DISCIPLINE             altera cartões, e pode expulsar

`NO_STRUCTURAL_EFFECT` NÃO É «IRRELEVANTE». Ele é «não muda ESTE estado». A
distinção importa: o PR-05.3 vai contar chutes a partir da mesma projeção
efetiva, e o fato de o reducer ignorá-los aqui não os torna menos canônicos.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.events.taxonomy import EventType


@final
class StructuralEffect(StrEnum):
    """O que um tipo de evento faz com o estado estrutural da partida."""

    NO_STRUCTURAL_EFFECT = "NO_STRUCTURAL_EFFECT"
    SCORE = "SCORE"
    SUBSTITUTION = "SUBSTITUTION"
    DISCIPLINE = "DISCIPLINE"

    @property
    def moves_state(self) -> bool:
        return self is not StructuralEffect.NO_STRUCTURAL_EFFECT


#: A CLASSIFICAÇÃO COMPLETA da taxonomia. Escrita por extenso, tipo a tipo —
#: uma regra derivada («tudo que não é gol nem cartão não faz nada») teria o
#: mesmo problema do `else`: ela classificaria o tipo novo sem ninguém decidir.
#:
#: TRÊS TIPOS MOVEM O ESTADO NESTA FASE, e cada um por um motivo esportivo:
#:
#:     GOAL          o placar é consequência dos gols efetivos, e de nada mais
#:     SUBSTITUTION  quem está em campo muda
#:     CARD          cartões contam, e expulsão tira jogador do campo
#:
#: `FOUL` e `OFFSIDE` NÃO estão aqui: eles são fatos do jogo que não alteram
#: placar, escalação nem disciplina — a falta que gera cartão vem acompanhada
#: de um `CARD` próprio, e é ele que conta.
_EFEITOS: Final[dict[EventType, StructuralEffect]] = {
    # ---- estruturais do relógio: marcam andamento, não estado
    EventType.MATCH_START: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.PERIOD_START: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.PERIOD_END: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.MATCH_END: StructuralEffect.NO_STRUCTURAL_EFFECT,
    # ---- ações com bola: são o insumo das features do PR-05.3
    EventType.PASS: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.CARRY: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.DRIBBLE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.SHOT: StructuralEffect.NO_STRUCTURAL_EFFECT,
    # ---- o gol
    EventType.GOAL: StructuralEffect.SCORE,
    # ---- ações defensivas
    EventType.PRESSURE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.RECOVERY: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.INTERCEPTION: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.TACKLE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.DUEL: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.BLOCK: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.CLEARANCE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    # ---- infrações
    EventType.FOUL: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.OFFSIDE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.CARD: StructuralEffect.DISCIPLINE,
    # ---- bola parada
    EventType.CORNER: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.FREE_KICK: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.THROW_IN: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.GOAL_KICK: StructuralEffect.NO_STRUCTURAL_EFFECT,
    # ---- elenco
    EventType.SUBSTITUTION: StructuralEffect.SUBSTITUTION,
    # ---- goleiro
    EventType.GOALKEEPER_ACTION: StructuralEffect.NO_STRUCTURAL_EFFECT,
    # ---- interrupções
    EventType.VAR: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.INJURY_STOPPAGE: StructuralEffect.NO_STRUCTURAL_EFFECT,
    EventType.GENERAL_STOPPAGE: StructuralEffect.NO_STRUCTURAL_EFFECT,
}


def _assert_exaustivo() -> None:
    """Falha NA IMPORTAÇÃO quando um tipo novo não foi classificado (§88).

    O LUGAR DA FALHA É O PONTO. Um tipo esquecido que só falhasse na hora de
    reconstruir um estado apareceria como uma partida específica quebrada, num
    lote de dez mil — e a investigação começaria pela partida, que é o lugar
    errado.
    """
    faltando = [tipo for tipo in EventType if tipo not in _EFEITOS]
    if faltando:
        nomes = ", ".join(sorted(t.value for t in faltando))
        raise RuntimeError(
            f"tipos de evento sem efeito estrutural declarado: {nomes}. Todo tipo "
            "precisa ser classificado — inclusive como NO_STRUCTURAL_EFFECT, que é "
            "uma decisão e não um esquecimento (PR-05.2 §87, §88)"
        )


_assert_exaustivo()


def structural_effect_of(event_type: EventType) -> StructuralEffect:
    """O efeito daquele tipo. Sem `default`, e é de propósito.

    `dict.get(tipo, NO_STRUCTURAL_EFFECT)` funcionaria e reintroduziria o
    problema: o tipo novo entraria como inofensivo sem ninguém decidir.
    """
    return _EFEITOS[event_type]


#: Os tipos que de fato movem o estado nesta fase. Ele é derivado do mapa — e
#: não escrito à mão — para que a lista não possa discordar da classificação.
STRUCTURAL_EVENT_TYPES: Final[frozenset[EventType]] = frozenset(
    tipo for tipo, efeito in _EFEITOS.items() if efeito.moves_state
)
