"""O construtor do estado — do corpus publicado ao `HistoricalMatchState`.

O FLUXO (§82), e cada passo existe por um motivo:

    1. valida a partida            evento e cotação de OUTRA partida são erro,
                                   e não linhas para filtrar em silêncio
    2. projeta os eventos          a autoridade é a `EffectiveEventProjection`
                                   do PR-05.1; este módulo não reimplementa
                                   revisão nem cancelamento
    3. filtra as cotações          pelo MESMO guarda temporal, nunca por uma
                                   comparação própria
    4. monta o estado inicial      placar zerado SÓ quando a cobertura prova o
                                   começo; escalação inicial quando publicada
    5. reduz os eventos            reducer puro, sem I/O
    6. fecha a disponibilidade     por componente
    7. monta a procedência         limitada, com digest
    8. imprime                     determinístico

ELE É DOMÍNIO E NÃO FAZ I/O (§73, §76). Recebe um `CanonicalMatchStateInput`
— que alguém já leu do corpus — e devolve estado mais problemas. Quem lê é a
camada de aplicação, e é lá que o banco existe.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field, replace
from typing import Final, final

from sports_intelligence.domain.events.canonical import CanonicalMatchEvent
from sports_intelligence.domain.events.details import CardDetail
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import (
    FactKind,
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.context import CorpusSource
from sports_intelligence.domain.features.leakage import (
    FactTiming,
    LeakageVerdict,
    TemporalLeakageGuard,
)
from sports_intelligence.domain.features.projection import (
    EffectiveEventProjection,
    EventKnowledge,
    ProjectionOutcome,
)
from sports_intelligence.domain.features.state.components import (
    DisciplinaryState,
    EventStructuralState,
    OddsQuoteState,
    OddsState,
    OnFieldState,
    ScoreState,
    TeamDisciplinaryState,
    TeamOnFieldState,
    decimal_as_text,
)
from sports_intelligence.domain.features.state.issues import (
    StateIssue,
    StateIssueCode,
)
from sports_intelligence.domain.features.state.match_state import (
    HistoricalMatchState,
    MatchContext,
    MatchStateIdentity,
)
from sports_intelligence.domain.features.state.provenance import MatchStateProvenance
from sports_intelligence.domain.features.state.reducer import (
    StateReducer,
    StructuralState,
    initial_structural_state,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf
from sports_intelligence.domain.matches.lineup import Lineup, LineupStatus
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.odds.models import CanonicalOddsObservation
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.canonical import canonical_json
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId

#: Quantos titulares uma escalação precisa declarar para que o estado em campo
#: possa ser AFIRMADO. Menos que isso é escalação parcial (§23): ela existe,
#: não se completa, e o campo não é afirmável a partir dela.
TITULARES_ESPERADOS: Final[int] = 11


@final
@dataclass(frozen=True, slots=True)
class CanonicalMatchStateInput:
    """Os fatos de UMA partida, como o corpus os publica (§77, §78).

    ELE É O QUE A LEITURA PRODUZ, e ainda não passou por filtro temporal: os
    eventos são CANDIDATOS — a história canônica inteira daquela partida —, e é
    o construtor que projeta. Entregá-los já filtrados aqui exigiria que quem
    lê conhecesse a política temporal, e a leitura passaria a ter opinião.

    `published_families` É O QUE A VERSÃO DECLARA. É por ela que «sem cartões»
    se distingue de «sem eventos publicados» (§40).
    """

    match: Match
    competition_code: str
    season_label: str
    published_families: frozenset[CoverageFamily] = frozenset()
    candidate_events: tuple[CanonicalMatchEvent, ...] = ()
    lineups: tuple[Lineup, ...] = ()
    odds: tuple[CanonicalOddsObservation, ...] = ()
    #: O resultado final. Ele NÃO alimenta o placar (§10, §12) — serve à
    #: conferência pós-jogo do §100, e só a ela.
    result: MatchResult | None = None
    #: Carimbos de conhecimento por evento, quando a fonte os tem (§26).
    knowledge: EventKnowledge = field(default_factory=EventKnowledge)

    def __post_init__(self) -> None:
        _recusar_fora_da_partida(
            self.match.id,
            eventos=self.candidate_events,
            escalacoes=self.lineups,
            cotacoes=self.odds,
        )

    def publishes(self, family: CoverageFamily) -> bool:
        return family in self.published_families


@final
@dataclass(frozen=True, slots=True)
class MatchStateBuildResult:
    """O estado mais o que houve de errado ao reconstruí-lo (§166).

    OS PROBLEMAS NÃO FICAM ESCONDIDOS DENTRO DO ESTADO. Eles estão nos dois
    lugares — no estado, porque fazem parte do que ele é; e aqui, porque quem
    chamou precisa poder contá-los sem abrir cada estado.
    """

    state: HistoricalMatchState
    issues: tuple[StateIssue, ...] = ()
    #: A PROJEÇÃO QUE PRODUZIU ESTE ESTADO (PR-05.3 §5, §91). Ela sai daqui
    #: para que a extração de features use EXATAMENTE os mesmos fatos
    #: efetivos — e não uma segunda projeção sobre a mesma entrada.
    #:
    #: DUAS PROJEÇÕES SERIAM DUAS VERDADES. Elas concordariam em todo caso
    #: fácil e divergiriam no difícil — a correção cujo carimbo está na
    #: fronteira do corte —, e a divergência apareceria como um estado que diz
    #: 1-1 ao lado de uma feature que contou dois gols.
    projection: ProjectionOutcome = field(default_factory=ProjectionOutcome)

    @property
    def is_partial(self) -> bool:
        return self.state.is_partial


@final
@dataclass(frozen=True, slots=True)
class HistoricalMatchStateBuilder:
    """Reconstrói o estado de uma partida num corte (§72).

    ELE NÃO CHAMA `FeatureCalculator` (§169). A relação será a inversa: o
    estado alimenta as features, e não o contrário. Um builder que calculasse
    features embutiria interpretação dentro de um fato.
    """

    policy: TemporalAvailabilityPolicy

    def build(
        self,
        entrada: CanonicalMatchStateInput,
        *,
        as_of: FeatureAsOf,
        source: CorpusSource,
    ) -> MatchStateBuildResult:
        if entrada.match.id != as_of.match_id:
            raise ValidationError(
                f"o corte é de {as_of.match_id} e a entrada é de {entrada.match.id}"
            )

        projecao = EffectiveEventProjection.with_policy(self.policy).project(
            entrada.candidate_events, as_of=as_of, knowledge=entrada.knowledge
        )
        efetivos = tuple(p.event for p in projecao.events)

        problemas: list[StateIssue] = []
        inicial = self._estado_inicial(entrada, problemas)
        reduzido = StateReducer().apply_all(inicial, efetivos)
        problemas.extend(i for i in reduzido.issues if i not in problemas)

        odds, problemas_de_odds = self._odds(entrada, as_of)
        problemas.extend(problemas_de_odds)

        eventos = self._estado_dos_eventos(entrada, projecao)
        reduzido = self._fechar_disponibilidade(entrada, reduzido)
        problemas.extend(i for i in reduzido.issues if i not in problemas)

        if as_of.is_post_match and entrada.result is not None:
            divergencia = _conferir_resultado(reduzido.score, entrada.result)
            if divergencia is not None:
                problemas.append(divergencia)

        estado = HistoricalMatchState.of(
            identity=MatchStateIdentity(
                match_id=entrada.match.id,
                competition_id=entrada.match.competition_id,
                season_id=entrada.match.season_id,
                home_team_id=entrada.match.home_team_id,
                away_team_id=entrada.match.away_team_id,
            ),
            context=MatchContext(
                competition_code=entrada.competition_code,
                season_label=entrada.season_label,
                stage=None if entrada.match.stage is None else str(entrada.match.stage),
                venue=None if entrada.match.venue is None else entrada.match.venue.name,
                neutral_venue=entrada.match.neutral_venue,
                scheduled_kickoff=entrada.match.scheduled_kickoff,
            ),
            as_of=as_of,
            source=source,
            policy=self.policy,
            score=reduzido.score,
            on_field=reduzido.on_field,
            discipline=reduzido.discipline,
            substitutions=reduzido.substitutions,
            events=eventos,
            odds=odds,
            provenance=_procedencia(entrada, efetivos, odds),
            issues=tuple(problemas),
        )
        return MatchStateBuildResult(
            state=estado,
            issues=tuple(sorted(set(problemas))),
            projection=projecao,
        )

    # ------------------------------------------------- estado inicial --

    def _estado_inicial(
        self, entrada: CanonicalMatchStateInput, problemas: list[StateIssue]
    ) -> StructuralState:
        """O estado ANTES de qualquer evento (§13, §21, §22).

        `0-0` SÓ QUANDO A COBERTURA PROVA O COMEÇO. Sem a família `EVENT`
        publicada, «zero a zero» é uma afirmação que ninguém pode fazer — e a
        diferença entre `0-0 AVAILABLE` e placar indisponível é justamente o
        §14.
        """
        tem_eventos = entrada.publishes(CoverageFamily.EVENT)
        if tem_eventos:
            placar = ScoreState()
            disciplina_disponivel = FeatureAvailability.AVAILABLE
        else:
            placar = ScoreState(
                availability=FeatureAvailability.NOT_DECLARED,
                detail="a versão do corpus não publica a família EVENT",
            )
            disciplina_disponivel = FeatureAvailability.NOT_DECLARED
            problemas.append(
                StateIssue.degraded(
                    StateIssueCode.INCOMPLETE_EVENT_HISTORY,
                    "score",
                    "a versão não publica EVENT: o placar não é reconstruível",
                )
            )

        em_campo = self._campo_inicial(entrada, problemas)
        disciplina = DisciplinaryState(
            home=TeamDisciplinaryState(
                team_id=entrada.match.home_team_id, availability=disciplina_disponivel
            ),
            away=TeamDisciplinaryState(
                team_id=entrada.match.away_team_id, availability=disciplina_disponivel
            ),
        )
        return initial_structural_state(
            match_id=entrada.match.id,
            home_team_id=entrada.match.home_team_id,
            away_team_id=entrada.match.away_team_id,
            score=placar,
            on_field=em_campo,
            discipline=disciplina,
        )

    def _campo_inicial(
        self, entrada: CanonicalMatchStateInput, problemas: list[StateIssue]
    ) -> OnFieldState:
        """Os titulares publicados — a base do estado em campo (§21, §22, §23).

        A ESCALAÇÃO INICIAL NÃO É MUTADA. Ela é fato publicado; o que muda é o
        estado em campo, que nasce dela e segue seu próprio caminho.
        """
        if not entrada.publishes(CoverageFamily.LINEUP) or not entrada.lineups:
            problemas.append(
                StateIssue.degraded(
                    StateIssueCode.LINEUP_UNAVAILABLE,
                    "on_field",
                    "a versão não publica escalação para esta partida",
                )
            )
            return _campo_indisponivel(
                entrada, FeatureAvailability.NOT_DECLARED, "escalação não publicada"
            )

        por_time = {lineup.team_id: lineup for lineup in entrada.lineups}
        lados = []
        for time in (entrada.match.home_team_id, entrada.match.away_team_id):
            escalacao = por_time.get(time)
            if escalacao is None:
                problemas.append(
                    StateIssue.degraded(
                        StateIssueCode.LINEUP_UNAVAILABLE,
                        "on_field",
                        f"sem escalação do time {time}",
                    )
                )
                lados.append(
                    TeamOnFieldState(
                        team_id=time,
                        availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                        detail="escalação ausente para este time",
                    )
                )
                continue
            titulares = tuple(
                e.player_id for e in escalacao.entries if e.status is LineupStatus.STARTER
            )
            if len(titulares) != TITULARES_ESPERADOS:
                # ESCALAÇÃO PARCIAL NÃO SE COMPLETA (§23). Dez titulares
                # declarados não viram onze por conveniência, e afirmar o campo
                # a partir deles produziria um elenco que nunca existiu.
                problemas.append(
                    StateIssue.degraded(
                        StateIssueCode.LINEUP_INCOMPLETE,
                        "on_field",
                        f"time {time} com {len(titulares)} titular(es) declarado(s)",
                    )
                )
                lados.append(
                    TeamOnFieldState(
                        team_id=time,
                        availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                        detail=f"{len(titulares)} titulares declarados",
                    )
                )
                continue
            try:
                lados.append(TeamOnFieldState.of(time, titulares))
            except ValidationError as erro:
                # O TIPO RECUSOU O ELENCO (§25, §27): jogador repetido, ou mais
                # de onze. Isso é defeito do dado publicado, e o construtor o
                # converte em problema tipado em vez de deixar a exceção subir —
                # uma partida com escalação suja não pode derrubar a
                # reconstrução das outras nove mil e novecentas do lote.
                problemas.append(
                    StateIssue.degraded(
                        StateIssueCode.LINEUP_DUPLICATE_PLAYER, "on_field", str(erro)
                    )
                )
                lados.append(
                    TeamOnFieldState(
                        team_id=time,
                        availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                        detail="escalação recusada pelo contrato de campo",
                    )
                )

        try:
            return OnFieldState(home=lados[0], away=lados[1])
        except ValidationError as erro:
            # O MESMO JOGADOR NOS DOIS TIMES (§26). O tipo recusa; aqui isso
            # vira problema tipado e campo indisponível — e o PLACAR sobrevive,
            # que é o §106.
            problemas.append(
                StateIssue.degraded(StateIssueCode.PLAYER_IN_BOTH_TEAMS, "on_field", str(erro))
            )
            return _campo_indisponivel(
                entrada, FeatureAvailability.SOURCE_UNAVAILABLE, "jogador nos dois times"
            )

    # ------------------------------------------------------------ odds --

    def _odds(
        self, entrada: CanonicalMatchStateInput, as_of: FeatureAsOf
    ) -> tuple[OddsState, list[StateIssue]]:
        """As cotações conhecidas no corte — a ÚLTIMA de cada fluxo (§46 ao §53).

        O FILTRO É O GUARDA DO PR-05.1, e não uma comparação local: uma segunda
        regra temporal aqui divergiria da primeira no caso difícil, que é
        justamente o que ninguém testa.
        """
        problemas: list[StateIssue] = []
        if not entrada.publishes(CoverageFamily.ODDS):
            return (
                OddsState(
                    availability=FeatureAvailability.NOT_DECLARED,
                    detail="a versão do corpus não publica a família ODDS",
                ),
                problemas,
            )
        if not entrada.odds:
            return (
                OddsState(
                    availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                    detail="a família é publicada e esta partida não tem cotação",
                ),
                problemas,
            )

        guarda = TemporalLeakageGuard(policy=self.policy)
        elegiveis: list[CanonicalOddsObservation] = []
        desconhecidas = 0
        for observacao in entrada.odds:
            especie = (
                FactKind.ODDS_OBSERVATION
                if observacao.observed_at is not None
                else FactKind.ODDS_CLOSING
            )
            decisao = guarda.evaluate(
                FactTiming(kind=especie, knowledge=observacao.observed_at), as_of
            )
            if decisao.verdict is LeakageVerdict.ALLOWED:
                elegiveis.append(observacao)
            elif decisao.verdict is LeakageVerdict.UNKNOWN:
                desconhecidas += 1

        if desconhecidas:
            problemas.append(
                StateIssue.noted(
                    StateIssueCode.ODDS_TEMPORAL_UNKNOWN,
                    "odds",
                    f"{desconhecidas} cotação(ões) sem prova de disponibilidade",
                )
            )
        if not elegiveis:
            return (
                OddsState(
                    availability=FeatureAvailability.TEMPORALLY_UNAVAILABLE,
                    detail="há cotações publicadas e nenhuma elegível neste corte",
                ),
                problemas,
            )
        return OddsState.of(_ultimas_por_fluxo(elegiveis)), problemas

    # ------------------------------------------------------- eventos --

    @staticmethod
    def _estado_dos_eventos(
        entrada: CanonicalMatchStateInput, projecao: ProjectionOutcome
    ) -> EventStructuralState:
        if not entrada.publishes(CoverageFamily.EVENT):
            return EventStructuralState(availability=FeatureAvailability.NOT_DECLARED)
        ids = projecao.ids()
        ultimo = projecao.events[-1] if projecao.events else None
        return EventStructuralState(
            effective_count=len(ids),
            latest_event_id=None if ultimo is None else ultimo.id,
            latest_position=None if ultimo is None else ultimo.position,
            digest=_digest_de_ids(ids),
        )

    # ---------------------------------------------- disponibilidade --

    @staticmethod
    def _fechar_disponibilidade(
        entrada: CanonicalMatchStateInput, estado: StructuralState
    ) -> StructuralState:
        """Sem `EVENT`, o que depende de evento não pode ser afirmado (§40).

        «ZERO CARTÕES» É UM FATO SÓ QUANDO HÁ EVENTO PUBLICADO. Sem ele, a
        contagem zerada não é observação: é a ausência de qualquer observação.
        """
        if entrada.publishes(CoverageFamily.EVENT):
            return estado
        indisponivel = FeatureAvailability.NOT_DECLARED
        return replace(
            estado,
            discipline=DisciplinaryState(
                home=replace(estado.discipline.home, availability=indisponivel),
                away=replace(estado.discipline.away, availability=indisponivel),
            ),
            substitutions=replace(estado.substitutions, availability=indisponivel),
        )


# ------------------------------------------------------------ auxiliares --


def _campo_indisponivel(
    entrada: CanonicalMatchStateInput,
    availability: FeatureAvailability,
    detail: str,
) -> OnFieldState:
    return OnFieldState(
        home=TeamOnFieldState(
            team_id=entrada.match.home_team_id, availability=availability, detail=detail
        ),
        away=TeamOnFieldState(
            team_id=entrada.match.away_team_id, availability=availability, detail=detail
        ),
    )


def _ultimas_por_fluxo(
    observacoes: list[CanonicalOddsObservation],
) -> tuple[OddsQuoteState, ...]:
    """A última cotação conhecida de cada fluxo (§122, §123).

    O DESEMPATE É DETERMINÍSTICO E NÃO É A ORDEM DO BANCO: instante, depois a
    referência da observação de origem, depois o valor. Duas leituras do mesmo
    corpus precisam escolher a mesma cotação — senão o estado muda de
    identidade sem o conteúdo mudar.
    """
    por_fluxo: dict[tuple[str, str, str, str], OddsQuoteState] = {}
    for observacao in sorted(observacoes, key=_ordem_da_cotacao):
        cotacao = _para_cotacao(observacao)
        por_fluxo[cotacao.stream_key()] = cotacao
    return tuple(por_fluxo.values())


def _ordem_da_cotacao(observacao: CanonicalOddsObservation) -> tuple[str, str, str]:
    instante = "" if observacao.observed_at is None else observacao.observed_at.isoformat()
    return (
        instante,
        observacao.provenance.source_record_id or "",
        decimal_as_text(observacao.decimal_odds),
    )


def _para_cotacao(observacao: CanonicalOddsObservation) -> OddsQuoteState:
    if observacao.observed_at is None:  # pragma: no cover - o guarda já recusou
        raise ValidationError("cotação sem instante chegou ao estado")
    return OddsQuoteState(
        bookmaker=observacao.bookmaker.code,
        market=observacao.market.value,
        selection=observacao.selection.value,
        decimal_odds=decimal_as_text(observacao.decimal_odds),
        observed_at=observacao.observed_at,
        line=None if observacao.line is None else decimal_as_text(observacao.line),
        source_reference=observacao.provenance.source_record_id or "",
    )


def _digest_de_ids(ids: tuple[uuid.UUID, ...]) -> str:
    if not ids:
        return ""
    return hashlib.sha256(canonical_json(sorted(str(i) for i in ids))).hexdigest()


def _procedencia(
    entrada: CanonicalMatchStateInput,
    efetivos: tuple[CanonicalMatchEvent, ...],
    odds: OddsState,
) -> MatchStateProvenance:
    gols = [e.id for e in efetivos if e.type is EventType.GOAL]
    de_campo = [
        e.id
        for e in efetivos
        if e.type is EventType.SUBSTITUTION or (e.type is EventType.CARD and _expulsa(e))
    ]
    cartoes = [e.id for e in efetivos if e.type is EventType.CARD]
    return MatchStateProvenance.of(
        score_events=gols,
        on_field_events=de_campo,
        discipline_events=cartoes,
        effective_events=[e.id for e in efetivos],
        odds_references=[q.source_reference or str(q.stream_key()) for q in odds.quotes],
        initial_lineup_teams=[str(lineup.team_id) for lineup in entrada.lineups],
    )


def _expulsa(event: CanonicalMatchEvent) -> bool:
    from sports_intelligence.domain.events.details import CardType

    detalhe = event.detail
    return isinstance(detalhe, CardDetail) and detalhe.card_type in (
        CardType.SECOND_YELLOW,
        CardType.RED,
    )


def _conferir_resultado(score: ScoreState, result: MatchResult) -> StateIssue | None:
    """O placar reconstruído contra o resultado publicado (§100, §101).

    ELE NÃO CORRIGE NADA. A conferência é diagnóstico: quando os dois
    discordam, o estado continua sendo o que os eventos dizem, e o problema
    fica registrado. Usar o resultado para «consertar» o placar seria
    exatamente o vazamento que o §10 proíbe, com a desculpa de ser pós-jogo.
    """
    if not score.is_available or result.regular_time is None:
        return None
    esperado = (result.regular_time.home, result.regular_time.away)
    obtido = (score.regular.home, score.regular.away)
    if esperado == obtido:
        return None
    return StateIssue.noted(
        StateIssueCode.SCORE_RESULT_MISMATCH,
        "score",
        f"eventos dizem {obtido[0]}-{obtido[1]} e o resultado publicado diz "
        f"{esperado[0]}-{esperado[1]}",
    )


def _recusar_fora_da_partida(
    match_id: MatchId,
    *,
    eventos: tuple[CanonicalMatchEvent, ...],
    escalacoes: tuple[Lineup, ...],
    cotacoes: tuple[CanonicalOddsObservation, ...],
) -> None:
    """Fato de outra partida é ERRO, e não linha para descartar (§113 ao §115).

    Filtrar em silêncio produziria um estado plausível de um jogo que não é o
    pedido — e um estado plausível e errado é pior que nenhum, porque nada
    denuncia.
    """
    for evento in eventos:
        if evento.match_id != match_id:
            raise ValidationError(
                f"evento {evento.id} é da partida {evento.match_id}, e a entrada é de {match_id}"
            )
    for escalacao in escalacoes:
        if escalacao.match_id != match_id:
            raise ValidationError(
                f"escalação do time {escalacao.team_id} é da partida "
                f"{escalacao.match_id}, e a entrada é de {match_id}"
            )
    for cotacao in cotacoes:
        if cotacao.match_id != match_id:
            raise ValidationError(
                f"cotação de {cotacao.bookmaker.code} é da partida {cotacao.match_id}, "
                f"e a entrada é de {match_id}"
            )
