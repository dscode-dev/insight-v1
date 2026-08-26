"""O que deu errado ao reconstruir — sem consertar nada.

O PRINCÍPIO (§167): quando os fatos discordam, o motor NÃO escolhe. Uma
substituição cujo jogador não está em campo pode ser um evento fora de ordem,
uma escalação incompleta ou um erro da fonte — e as três exigem ações
diferentes. Reparar em silêncio produziria um estado plausível e falso, que é o
pior resultado possível porque nada denuncia.

CADA PROBLEMA DEGRADA O COMPONENTE AFETADO, e só ele (§105, §106). Cotação
indisponível não impede o placar; escalação ausente não impede o placar;
placar inconsistente com o resultado final não invalida o estado dos 63
minutos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self, final


@final
class StateIssueCode(StrEnum):
    """Catálogo FECHADO de problemas de reconstrução (§103)."""

    #: A cobertura de evento não prova a história desde o início da partida.
    INCOMPLETE_EVENT_HISTORY = "INCOMPLETE_EVENT_HISTORY"
    #: A versão não publica escalação para esta partida.
    LINEUP_UNAVAILABLE = "LINEUP_UNAVAILABLE"
    #: A escalação existe e não tem onze titulares — não se completa (§23).
    LINEUP_INCOMPLETE = "LINEUP_INCOMPLETE"
    #: O mesmo jogador aparece nos dois times (§26).
    PLAYER_IN_BOTH_TEAMS = "PLAYER_IN_BOTH_TEAMS"
    #: O mesmo jogador aparece duas vezes no MESMO time (§25). Quase sempre
    #: resolução de identidade que fundiu dois jogadores — e deduplicar em
    #: silêncio produziria um time de dez que a súmula diz ter onze.
    LINEUP_DUPLICATE_PLAYER = "LINEUP_DUPLICATE_PLAYER"
    #: Quem sai não estava em campo (§31).
    SUBSTITUTION_PLAYER_NOT_ON_FIELD = "SUBSTITUTION_PLAYER_NOT_ON_FIELD"
    #: Quem entra já estava em campo (§32).
    SUBSTITUTION_PLAYER_ALREADY_ON_FIELD = "SUBSTITUTION_PLAYER_ALREADY_ON_FIELD"
    #: A substituição não diz quem sai e quem entra.
    SUBSTITUTION_WITHOUT_PLAYERS = "SUBSTITUTION_WITHOUT_PLAYERS"
    #: O expulso não estava em campo.
    DISMISSAL_PLAYER_NOT_ON_FIELD = "DISMISSAL_PLAYER_NOT_ON_FIELD"
    #: A expulsão não identifica o jogador (§39).
    DISMISSAL_PLAYER_UNKNOWN = "DISMISSAL_PLAYER_UNKNOWN"
    #: A transição resultaria em mais de onze em campo (§27, §144).
    ON_FIELD_OVER_ELEVEN = "ON_FIELD_OVER_ELEVEN"
    #: O gol é de um time que não joga esta partida.
    GOAL_TEAM_UNRESOLVED = "GOAL_TEAM_UNRESOLVED"
    #: O placar reconstruído difere do resultado final publicado (§101).
    SCORE_RESULT_MISMATCH = "SCORE_RESULT_MISMATCH"
    #: Há cotação e não dá para provar que era conhecida (§51).
    ODDS_TEMPORAL_UNKNOWN = "ODDS_TEMPORAL_UNKNOWN"


@final
class StateIssueSeverity(StrEnum):
    """Quanto o problema compromete o estado (§104).

    A SEVERIDADE É DO PROBLEMA, e não de quem o lê. `DEGRADED` significa que um
    componente ficou indisponível; `NOTED` significa que o estado está inteiro e
    alguém precisa saber de algo — o placar que não bate com o resultado final,
    por exemplo, não muda o estado dos 63 minutos.
    """

    NOTED = "NOTED"
    DEGRADED = "DEGRADED"


@final
@dataclass(frozen=True, slots=True, order=True)
class StateIssue:
    """UM problema, com o componente que ele atingiu e o detalhe."""

    code: StateIssueCode
    severity: StateIssueSeverity
    component: str
    detail: str = ""

    @classmethod
    def degraded(cls, code: StateIssueCode, component: str, detail: str = "") -> Self:
        return cls(
            code=code,
            severity=StateIssueSeverity.DEGRADED,
            component=component,
            detail=detail,
        )

    @classmethod
    def noted(cls, code: StateIssueCode, component: str, detail: str = "") -> Self:
        return cls(code=code, severity=StateIssueSeverity.NOTED, component=component, detail=detail)

    def as_canonical(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "component": self.component,
            "severity": self.severity.value,
        }

    def __str__(self) -> str:
        return f"{self.code.value}@{self.component}" + (f" ({self.detail})" if self.detail else "")
