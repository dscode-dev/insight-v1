"""A redução pura — de fatos efetivos a estado estrutural.

    State_t = Reduce(InitialState, EffectiveFacts<=t)

O REDUCER NÃO DECIDE O QUE É EFETIVO (§17, §18, §45). Gol cancelado não chega
aqui; correção não conhecida não chega aqui. Quem decide é a
`EffectiveEventProjection` do PR-05.1, e reimplementar a lógica de revisão
neste módulo criaria uma segunda autoridade sobre a mesma pergunta — que
divergiria da primeira no primeiro caso difícil.

ELE É PURO (§73). Recebe estado e fato, devolve estado novo. Sem I/O, sem
relógio, sem repositório, sem sorteio. É essa propriedade que permite provar
as invariantes do PR sobre conjuntos inteiros de entrada.

NÃO REPARA NADA (§167). Quando os fatos discordam — uma substituição cujo
jogador não está em campo, uma transição que resultaria em doze —, o reducer
registra o problema e DEGRADA o componente. Ele não escolhe uma leitura
plausível: escolher produziria um estado que parece certo e não é, e nada no
resultado denunciaria a escolha.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.details import CardDetail, CardType, SubstitutionDetail
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.state.components import (
    MAX_EM_CAMPO,
    AppliedSubstitution,
    DisciplinaryState,
    OnFieldState,
    ScoreState,
    SubstitutionState,
    Tally,
)
from sports_intelligence.domain.features.state.effects import (
    StructuralEffect,
    structural_effect_of,
)
from sports_intelligence.domain.features.state.issues import StateIssue, StateIssueCode
from sports_intelligence.domain.features.temporal import MatchTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId, TeamId
from sports_intelligence.domain.shared.temporal import Period

#: Os cartões que EXPULSAM. `SECOND_YELLOW` está aqui e também conta como
#: amarelo: ele é as duas coisas, e contá-lo só como expulsão faria a soma de
#: amarelos do time ficar menor que a súmula (§38).
_EXPULSAM: frozenset[CardType] = frozenset({CardType.SECOND_YELLOW, CardType.RED})

#: Os cartões que contam como AMARELO.
_AMARELOS: frozenset[CardType] = frozenset({CardType.YELLOW, CardType.SECOND_YELLOW})


@final
@dataclass(frozen=True, slots=True)
class StructuralState:
    """O que o reducer transforma — os componentes que os eventos movem.

    ELE NÃO É O `HistoricalMatchState`. O estado completo tem contexto,
    identidade, origem, odds e procedência; o reducer só precisa da parte que
    os eventos mudam, e recebê-la inteira o obrigaria a saber de coisas que
    não lhe dizem respeito.
    """

    match_id: MatchId
    home_team_id: TeamId
    away_team_id: TeamId
    score: ScoreState
    on_field: OnFieldState
    discipline: DisciplinaryState
    substitutions: SubstitutionState
    issues: tuple[StateIssue, ...] = ()

    def with_issue(self, issue: StateIssue) -> StructuralState:
        """Acrescenta o problema SEM repeti-lo.

        Um mesmo defeito estrutural — escalação ausente, por exemplo — apareceria
        uma vez por evento aplicado, e a lista de problemas viraria ruído onde
        deveria haver diagnóstico.
        """
        if issue in self.issues:
            return self
        return replace(self, issues=(*self.issues, issue))

    def side_of(self, team_id: TeamId | None) -> str | None:
        """`"HOME"`, `"AWAY"` ou `None` quando o time não joga esta partida."""
        if team_id is None:
            return None
        if team_id == self.home_team_id:
            return "HOME"
        if team_id == self.away_team_id:
            return "AWAY"
        return None


@final
@dataclass(frozen=True, slots=True)
class StateReducer:
    """Aplica UM fato efetivo ao estado. Puro (§73, §83).

    O DESPACHO É POR EFEITO ESTRUTURAL DECLARADO, e não por comparação de
    string (§83, §87). Um `if event.type == "goal"` espalhado teria dois
    defeitos: erraria silenciosamente com um tipo novo, e espalharia a decisão
    por tantos lugares quantos fossem os `if`.
    """

    #: Se a história de eventos é completa o bastante para AFIRMAR o placar.
    #: Sem isso, o reducer conta os gols que viu — e o construtor do estado
    #: marca o placar como não afirmável (§13, §14).
    def apply(self, state: StructuralState, event: CanonicalMatchEvent) -> StructuralState:
        if event.match_id != state.match_id:
            # NÃO FILTRA EM SILÊNCIO (§113). Um evento de outra partida entrando
            # num estado produziria um jogo plausível que não aconteceu.
            raise ValidationError(
                f"evento {event.id} é da partida {event.match_id} e o estado é de "
                f"{state.match_id}",
                context={"event_id": str(event.id), "match_id": str(state.match_id)},
            )
        efeito = structural_effect_of(event.type)
        if efeito is StructuralEffect.NO_STRUCTURAL_EFFECT:
            # ELE CONTINUA SENDO UM FATO (§84). O chute está na projeção
            # efetiva e alimentará as features do PR-05.3; o que ele não faz é
            # mover placar, campo ou disciplina.
            return state
        if efeito is StructuralEffect.SCORE:
            return self._gol(state, event)
        if efeito is StructuralEffect.SUBSTITUTION:
            return self._substituicao(state, event)
        return self._cartao(state, event)

    def apply_all(
        self, state: StructuralState, events: tuple[CanonicalMatchEvent, ...]
    ) -> StructuralState:
        """Aplica em sequência. A ORDEM É A DA PROJEÇÃO, e não a da entrada.

        Ela já vem canônica de lá — `(fase, minuto, acréscimo, sequência, id)`
        —, e reordenar aqui esconderia uma projeção desordenada em vez de
        denunciá-la.
        """
        atual = state
        for evento in events:
            atual = self.apply(atual, evento)
        return atual

    # ------------------------------------------------------------- gol --

    @staticmethod
    def _gol(state: StructuralState, event: CanonicalMatchEvent) -> StructuralState:
        """O gol move o placar — pelo TIME CREDITADO no evento canônico (§15).

        O MODELO CANÔNICO NÃO MARCA GOL CONTRA (§16). `EventType` não tem
        `OWN_GOAL` e `ShotDetail` não tem indicador; o que existe é o `team_id`
        do evento, e ele é o time A QUEM O GOL É CREDITADO. Deduzir o lado pelo
        time do jogador seria exatamente a suposição que o §16 proíbe — num gol
        contra, o jogador é de um lado e o ponto é do outro.
        """
        lado = state.side_of(event.team_id)
        if lado is None:
            # FAIL-CLOSED (§112). Um gol que não se sabe de quem é torna o
            # placar inteiro não afirmável — somar num lado ao acaso seria pior.
            return replace(
                state,
                score=state.score.unavailable(
                    FeatureAvailability.SOURCE_UNAVAILABLE,
                    f"gol {event.id} creditado a um time que não joga esta partida",
                ),
            ).with_issue(
                StateIssue.degraded(
                    StateIssueCode.GOAL_TEAM_UNRESOLVED,
                    "score",
                    f"evento {event.id}",
                )
            )
        if not state.score.is_available:
            # O placar já foi invalidado; aplicar mais gols sobre ele produziria
            # um número que ninguém pode usar.
            return state

        periodo = event.clock.period
        if periodo is Period.PENALTY_SHOOTOUT:
            # A DISPUTA NÃO ENTRA NO PLACAR (§19, §98). «2-1, 4-3 nos pênaltis»
            # são dois resultados, e somá-los produziria 6-4, que não existiu.
            atual = state.score.shootout
            novo = atual.plus_home() if lado == "HOME" else atual.plus_away()
            return replace(state, score=_com_shootout(state.score, novo))
        if periodo in (Period.EXTRA_TIME_FIRST, Period.EXTRA_TIME_SECOND):
            atual = state.score.extra_time
            novo = atual.plus_home() if lado == "HOME" else atual.plus_away()
            return replace(state, score=_com_prorrogacao(state.score, novo))
        atual = state.score.regular
        novo = atual.plus_home() if lado == "HOME" else atual.plus_away()
        return replace(state, score=_com_normal(state.score, novo))

    # ---------------------------------------------------- substituição --

    @staticmethod
    def _substituicao(
        state: StructuralState, event: CanonicalMatchEvent
    ) -> StructuralState:
        """Quem sai sai, quem entra entra — e nada é adivinhado (§29 ao §33)."""
        detalhe = event.detail
        if not isinstance(detalhe, SubstitutionDetail) or event.team_id is None:
            return _degradar_campo(
                state,
                event.team_id,
                StateIssueCode.SUBSTITUTION_WITHOUT_PLAYERS,
                f"substituição {event.id} sem detalhe tipado ou sem time",
            )
        em_campo = state.on_field.team(event.team_id)
        if em_campo is None:
            return state.with_issue(
                StateIssue.degraded(
                    StateIssueCode.SUBSTITUTION_PLAYER_NOT_ON_FIELD,
                    "on_field",
                    f"time {event.team_id} não joga esta partida",
                )
            )
        if not em_campo.is_available:
            # SEM ESCALAÇÃO NÃO HÁ CAMPO PARA MUDAR (§33). A substituição
            # continua no histórico — ela aconteceu —, e o campo segue
            # indisponível.
            return _com_substituicao_registrada(state, event, detalhe)

        if not em_campo.has(detalhe.player_out):
            return _degradar_campo(
                state,
                event.team_id,
                StateIssueCode.SUBSTITUTION_PLAYER_NOT_ON_FIELD,
                f"{detalhe.player_out} não estava em campo na substituição {event.id}",
            )
        if em_campo.has(detalhe.player_in):
            return _degradar_campo(
                state,
                event.team_id,
                StateIssueCode.SUBSTITUTION_PLAYER_ALREADY_ON_FIELD,
                f"{detalhe.player_in} já estava em campo na substituição {event.id}",
            )

        jogadores = tuple(p for p in em_campo.players if p != detalhe.player_out)
        jogadores = (*jogadores, detalhe.player_in)
        if len(jogadores) > MAX_EM_CAMPO:
            # NÃO SE CORTA A LISTA (§27, §144). Doze em campo é conflito, e
            # escolher quem sai seria inventar a resposta.
            return _degradar_campo(
                state,
                event.team_id,
                StateIssueCode.ON_FIELD_OVER_ELEVEN,
                f"a substituição {event.id} resultaria em {len(jogadores)} em campo",
            )
        atualizado = em_campo.with_players(jogadores)
        return _com_substituicao_registrada(
            replace(state, on_field=state.on_field.with_team(atualizado)), event, detalhe
        )

    # --------------------------------------------------------- cartão --

    @staticmethod
    def _cartao(state: StructuralState, event: CanonicalMatchEvent) -> StructuralState:
        """Amarelo conta; expulsão conta e tira do campo (§36, §37, §38, §39)."""
        detalhe = event.detail
        if not isinstance(detalhe, CardDetail) or event.team_id is None:
            return state.with_issue(
                StateIssue.noted(
                    StateIssueCode.DISMISSAL_PLAYER_UNKNOWN,
                    "discipline",
                    f"cartão {event.id} sem detalhe tipado ou sem time",
                )
            )
        do_time = state.discipline.team(event.team_id)
        if do_time is None:
            return state.with_issue(
                StateIssue.noted(
                    StateIssueCode.DISMISSAL_PLAYER_UNKNOWN,
                    "discipline",
                    f"cartão {event.id} de um time que não joga esta partida",
                )
            )

        atualizado = do_time
        if detalhe.card_type in _AMARELOS:
            atualizado = atualizado.plus_yellow()
        if detalhe.card_type not in _EXPULSAM:
            # AMARELO NÃO TIRA NINGUÉM DE CAMPO (§36).
            return replace(state, discipline=state.discipline.with_team(atualizado))

        atualizado = atualizado.plus_dismissal(event.player_id)
        com_disciplina = replace(state, discipline=state.discipline.with_team(atualizado))

        if event.player_id is None:
            # O TIME PERDEU UM JOGADOR E NÃO SE SABE QUEM (§39). A disciplina
            # registra; o campo não pode ser afirmado, e ajustar só a contagem
            # produziria um elenco de dez nomes conhecidos e um fantasma.
            return _degradar_campo(
                com_disciplina,
                event.team_id,
                StateIssueCode.DISMISSAL_PLAYER_UNKNOWN,
                f"expulsão {event.id} sem jogador identificado",
            )
        em_campo = com_disciplina.on_field.team(event.team_id)
        if em_campo is None or not em_campo.is_available:
            return com_disciplina
        if not em_campo.has(event.player_id):
            return _degradar_campo(
                com_disciplina,
                event.team_id,
                StateIssueCode.DISMISSAL_PLAYER_NOT_ON_FIELD,
                f"{event.player_id} não estava em campo na expulsão {event.id}",
            )
        restantes = tuple(p for p in em_campo.players if p != event.player_id)
        return replace(
            com_disciplina,
            on_field=com_disciplina.on_field.with_team(em_campo.with_players(restantes)),
        )


# ------------------------------------------------------------- auxiliares --


def _com_normal(score: ScoreState, tally: Tally) -> ScoreState:
    return replace(score, regular=tally)


def _com_prorrogacao(score: ScoreState, tally: Tally) -> ScoreState:
    return replace(score, extra_time=tally)


def _com_shootout(score: ScoreState, tally: Tally) -> ScoreState:
    return replace(score, shootout=tally)


def _degradar_campo(
    state: StructuralState,
    team_id: TeamId | None,
    code: StateIssueCode,
    detail: str,
) -> StructuralState:
    """Marca o campo daquele time como não afirmável, com motivo.

    SÓ O TIME AFETADO (§106). Um conflito no elenco do mandante não diz nada
    sobre quem está em campo pelo visitante — e derrubar os dois transformaria
    um problema em dois.
    """
    com_problema = state.with_issue(StateIssue.degraded(code, "on_field", detail))
    if team_id is None:
        return com_problema
    em_campo = com_problema.on_field.team(team_id)
    if em_campo is None:
        return com_problema
    degradado = em_campo.degraded(FeatureAvailability.SOURCE_UNAVAILABLE, detail)
    return replace(com_problema, on_field=com_problema.on_field.with_team(degradado))


def _com_substituicao_registrada(
    state: StructuralState,
    event: CanonicalMatchEvent,
    detalhe: SubstitutionDetail,
) -> StructuralState:
    """A substituição entra no histórico mesmo quando o campo não é afirmável.

    ELA ACONTECEU (§33). O que pode faltar é a base para dizer quem está em
    campo — e apagar o histórico junto perderia um fato que o corpus tem.
    """
    aplicada = AppliedSubstitution(
        event_id=event.id,
        team_id=_time_obrigatorio(event),
        player_out=detalhe.player_out,
        player_in=detalhe.player_in,
        at=MatchTimePoint.from_clock(event.clock, sequence=event.sequence),
    )
    return replace(state, substitutions=state.substitutions.plus(aplicada))


def _time_obrigatorio(event: CanonicalMatchEvent) -> TeamId:
    if event.team_id is None:  # pragma: no cover - o domínio de evento já exige
        raise ValidationError(f"substituição {event.id} sem time")
    return event.team_id


def initial_structural_state(
    *,
    match_id: MatchId,
    home_team_id: TeamId,
    away_team_id: TeamId,
    score: ScoreState,
    on_field: OnFieldState,
    discipline: DisciplinaryState,
) -> StructuralState:
    """O estado ANTES de qualquer evento (§13).

    `0-0` NÃO É O PADRÃO UNIVERSAL. Ele é o placar de uma partida cuja história
    de eventos começa no apito inicial; quando a cobertura não prova isso, quem
    constrói o estado entrega um `ScoreState` indisponível — e este construtor
    aceita o que lhe derem, em vez de decidir por conta própria.
    """
    return StructuralState(
        match_id=match_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        score=score,
        on_field=on_field,
        discipline=discipline,
        substitutions=SubstitutionState(),
    )


def _tipos_estruturais() -> tuple[EventType, ...]:
    """Os tipos que o reducer trata — derivados do catálogo, nunca escritos.

    Ela existe para o teste table-driven do §146: a tabela de transições é
    montada a partir DESTA lista, então um tipo estrutural novo aparece no
    teste sem ninguém lembrar de acrescentá-lo.
    """
    from sports_intelligence.domain.features.state.effects import STRUCTURAL_EVENT_TYPES

    return tuple(sorted(STRUCTURAL_EVENT_TYPES, key=lambda t: t.value))


STRUCTURAL_TYPES_HANDLED = _tipos_estruturais()
