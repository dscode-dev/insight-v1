"""O ciclo de vida de uma partida, e a regra que impede uma se descrever.

O CICLO NORMAL segue o princípio central do motor: toda partida ao vivo é
também um dataset histórico futuro.

    DISCOVERED → SCHEDULED → PRE_MATCH → LIVE
      → FINISHED_PENDING_RECONCILIATION → RECONCILED
      → HISTORICAL_PENDING_BUILD → HISTORICAL_ACTIVE

O INVARIANTE QUE ESTE MÓDULO EXISTE PARA IMPOR está no fim dessa cadeia. Só
partidas em `HISTORICAL_ACTIVE` podem alimentar o índice consultado por uma
partida ao vivo. Sem isso acontece self-leakage: a partida em andamento acha a
si mesma — ou a uma versão parcial de si mesma — entre os "jogos históricos
parecidos", e a similaridade fica excelente descrevendo nada.

O sintoma é traiçoeiro porque é bom: as métricas SOBEM. Um sistema que se
consulta acerta muito, até ir para produção contra partidas que ele nunca viu.

TRANSIÇÕES EXPLÍCITAS, E NÃO UM CAMPO LIVRE. `match.status = "LIVE"` compila,
passa no type checker e permite que uma partida cancelada volte a ficar ao
vivo. O grafo abaixo é a lista fechada do que pode acontecer, e `transition_to`
é a única porta.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, final

from sports_intelligence.domain.shared.errors import InvariantViolationError
from sports_intelligence.domain.shared.temporal import Instant


class MatchLifecycle(StrEnum):
    """Onde a partida está no ciclo. Um estado, nunca uma combinação."""

    #: Existe segundo alguma fonte; ainda não confirmada nem datada.
    DISCOVERED = "DISCOVERED"
    SCHEDULED = "SCHEDULED"
    #: Janela pré-jogo: escalações, mercado, contexto. Ainda não rolou a bola.
    PRE_MATCH = "PRE_MATCH"
    LIVE = "LIVE"
    #: Acabou; o que temos ainda é o fluxo ao vivo, que costuma ter buracos.
    FINISHED_PENDING_RECONCILIATION = "FINISHED_PENDING_RECONCILIATION"
    #: Conferida contra as fontes definitivas. Os fatos estão fechados.
    RECONCILED = "RECONCILED"
    #: Fatos fechados; features e vetores ainda não construídos.
    HISTORICAL_PENDING_BUILD = "HISTORICAL_PENDING_BUILD"
    #: O ÚNICO estado que pode alimentar retrieval histórico.
    HISTORICAL_ACTIVE = "HISTORICAL_ACTIVE"

    # -- estados excepcionais: saem do fluxo e não voltam sozinhos --
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"
    #: Os dados se contradizem a ponto de não dar para fechar os fatos.
    DATA_INVALID = "DATA_INVALID"
    #: Precisa de um humano. Estado de espera, não de fim.
    REVIEW_REQUIRED = "REVIEW_REQUIRED"

    @property
    def is_terminal(self) -> bool:
        """Estados dos quais nada mais sai."""
        return self in _TERMINAIS

    @property
    def is_exceptional(self) -> bool:
        return self in _EXCEPCIONAIS

    @property
    def is_live_or_upcoming(self) -> bool:
        """Se a partida ainda pode gerar estado ao vivo."""
        return self in (
            MatchLifecycle.SCHEDULED,
            MatchLifecycle.PRE_MATCH,
            MatchLifecycle.LIVE,
        )

    @property
    def can_feed_historical_index(self) -> bool:
        """A regra do ADR-0007, num lugar só.

        Escrita como propriedade do estado — e não como um `if` no ponto de
        consulta — porque um `if` espalhado por três consultas vira três
        políticas que divergem na primeira vez que alguém ajusta uma.
        """
        return self is MatchLifecycle.HISTORICAL_ACTIVE


_TERMINAIS: Final = frozenset(
    {
        MatchLifecycle.HISTORICAL_ACTIVE,
        MatchLifecycle.CANCELLED,
    }
)

_EXCEPCIONAIS: Final = frozenset(
    {
        MatchLifecycle.POSTPONED,
        MatchLifecycle.CANCELLED,
        MatchLifecycle.ABANDONED,
        MatchLifecycle.DATA_INVALID,
        MatchLifecycle.REVIEW_REQUIRED,
    }
)


#: O grafo. Lista fechada: o que não está aqui não acontece.
#:
#: ALGUMAS ARESTAS MERECEM NOTA:
#:
#: `HISTORICAL_ACTIVE` não sai para lugar nenhum. Uma partida já indexada que
#: precise mudar exige reconstrução do índice, que é uma operação
#: administrativa deliberada — não uma transição de estado que um worker
#: dispara sozinho.
#:
#: `POSTPONED` volta para `SCHEDULED`: adiada é remarcada, e é a mesma
#: partida. `CANCELLED` não volta de lugar nenhum.
#:
#: `ABANDONED` (interrompida em campo) vai para reconciliação, não para o
#: lixo: o que aconteceu até a interrupção é fato, e às vezes o resultado é
#: homologado depois.
#:
#: `REVIEW_REQUIRED` sai para os três estados de fechamento porque o humano
#: pode decidir três coisas: seguir, invalidar, ou marcar como abandonada.
_TRANSICOES: Final[dict[MatchLifecycle, frozenset[MatchLifecycle]]] = {
    MatchLifecycle.DISCOVERED: frozenset(
        {
            MatchLifecycle.SCHEDULED,
            MatchLifecycle.CANCELLED,
            MatchLifecycle.DATA_INVALID,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.SCHEDULED: frozenset(
        {
            MatchLifecycle.PRE_MATCH,
            MatchLifecycle.POSTPONED,
            MatchLifecycle.CANCELLED,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.PRE_MATCH: frozenset(
        {
            MatchLifecycle.LIVE,
            MatchLifecycle.POSTPONED,
            MatchLifecycle.CANCELLED,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.LIVE: frozenset(
        {
            MatchLifecycle.FINISHED_PENDING_RECONCILIATION,
            MatchLifecycle.ABANDONED,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.FINISHED_PENDING_RECONCILIATION: frozenset(
        {
            MatchLifecycle.RECONCILED,
            MatchLifecycle.DATA_INVALID,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.RECONCILED: frozenset(
        {
            MatchLifecycle.HISTORICAL_PENDING_BUILD,
            MatchLifecycle.DATA_INVALID,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.HISTORICAL_PENDING_BUILD: frozenset(
        {
            MatchLifecycle.HISTORICAL_ACTIVE,
            MatchLifecycle.DATA_INVALID,
            MatchLifecycle.REVIEW_REQUIRED,
        }
    ),
    MatchLifecycle.HISTORICAL_ACTIVE: frozenset(),
    MatchLifecycle.POSTPONED: frozenset({MatchLifecycle.SCHEDULED, MatchLifecycle.CANCELLED}),
    MatchLifecycle.CANCELLED: frozenset(),
    MatchLifecycle.ABANDONED: frozenset(
        {
            MatchLifecycle.FINISHED_PENDING_RECONCILIATION,
            MatchLifecycle.DATA_INVALID,
        }
    ),
    MatchLifecycle.DATA_INVALID: frozenset({MatchLifecycle.REVIEW_REQUIRED}),
    MatchLifecycle.REVIEW_REQUIRED: frozenset(
        {
            MatchLifecycle.SCHEDULED,
            MatchLifecycle.PRE_MATCH,
            MatchLifecycle.LIVE,
            MatchLifecycle.FINISHED_PENDING_RECONCILIATION,
            MatchLifecycle.RECONCILED,
            MatchLifecycle.HISTORICAL_PENDING_BUILD,
            MatchLifecycle.CANCELLED,
            MatchLifecycle.ABANDONED,
            MatchLifecycle.DATA_INVALID,
        }
    ),
}


class IllegalTransitionError(InvariantViolationError):
    """Uma transição fora do grafo. Sempre defeito nosso, nunca entrada ruim."""


@final
@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    """Uma transição que aconteceu — com quando e por quê.

    O MOTIVO É OBRIGATÓRIO. "Por que esta partida virou DATA_INVALID às
    03:14?" é a primeira pergunta de todo incidente, e uma transição sem
    motivo a deixa sem resposta.
    """

    from_state: MatchLifecycle
    to_state: MatchLifecycle
    at: Instant
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise ValueError("toda transição precisa de motivo")


def can_transition(current: MatchLifecycle, target: MatchLifecycle) -> bool:
    return target in _TRANSICOES[current]


def allowed_transitions(current: MatchLifecycle) -> frozenset[MatchLifecycle]:
    return _TRANSICOES[current]


def transition_to(
    current: MatchLifecycle, target: MatchLifecycle, *, at: Instant, reason: str
) -> LifecycleTransition:
    """A ÚNICA porta para mudar de estado.

    Recusa nomeando o que era possível: "transição inválida" manda quem lê ir
    procurar o grafo; listar os alvos permitidos resolve na mesma linha.
    """
    if not can_transition(current, target):
        permitidos = sorted(t.value for t in _TRANSICOES[current])
        raise IllegalTransitionError(
            f"{current} não pode ir para {target}",
            context={
                "from": current.value,
                "to": target.value,
                "allowed": permitidos or ["(nenhum: estado terminal)"],
            },
        )
    return LifecycleTransition(from_state=current, to_state=target, at=at, reason=reason.strip())


def assert_can_feed_historical_index(state: MatchLifecycle) -> None:
    """O INVARIANTE DE ADR-0007, aplicável em uma linha.

    Chamado por quem monta o conjunto de candidatos do retrieval histórico.
    Deixar a checagem implícita — confiando que a consulta filtre por estado —
    funciona até alguém escrever uma segunda consulta.
    """
    if not state.can_feed_historical_index:
        raise InvariantViolationError(
            "partida em estado não histórico foi oferecida ao índice histórico",
            context={
                "state": state.value,
                "required": MatchLifecycle.HISTORICAL_ACTIVE.value,
                "why": (
                    "uma partida ao vivo presente no índice que ela própria consulta "
                    "encontra a si mesma — a similaridade fica excelente e não descreve nada"
                ),
            },
        )
