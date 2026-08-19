"""O reducer, tipo a tipo — a tabela do §146 e a exaustividade do §147.

DUAS COISAS DIFERENTES SÃO PROVADAS AQUI:

    1. que CADA tipo classificado como estrutural produz a transição correta
    2. que a CLASSIFICAÇÃO é completa — nenhum `EventType` fica sem decisão

A segunda é a que sobrevive ao tempo. A primeira testa o que existe hoje; a
segunda quebra no dia em que a taxonomia ganhar um tipo e ninguém disser o que
ele faz com o estado — que é exatamente o defeito que o §88 existe para
impedir, e que um `else` silencioso deixaria passar.
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.events.details import CardType
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.state.components import (
    DisciplinaryState,
    OnFieldState,
    ScoreState,
    TeamDisciplinaryState,
    TeamOnFieldState,
)
from sports_intelligence.domain.features.state.effects import (
    STRUCTURAL_EVENT_TYPES,
    StructuralEffect,
    structural_effect_of,
)
from sports_intelligence.domain.features.state.issues import (
    StateIssue,
    StateIssueCode,
    StateIssueSeverity,
)
from sports_intelligence.domain.features.state.reducer import (
    StateReducer,
    StructuralState,
    initial_structural_state,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId, TeamId
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import CASA, FORA, PARTIDA
from tests.support.state_fixtures import (
    CASA_BANCO,
    CASA_TITULARES,
    FORA_BANCO,
    FORA_TITULARES,
    evento,
)


def estado_inicial() -> StructuralState:
    """Onze de cada lado, placar zerado, disciplina disponível."""
    return initial_structural_state(
        match_id=PARTIDA,
        home_team_id=CASA,
        away_team_id=FORA,
        score=ScoreState(),
        on_field=OnFieldState(
            home=TeamOnFieldState.of(CASA, CASA_TITULARES),
            away=TeamOnFieldState.of(FORA, FORA_TITULARES),
        ),
        discipline=DisciplinaryState(
            home=TeamDisciplinaryState(team_id=CASA),
            away=TeamDisciplinaryState(team_id=FORA),
        ),
    )


def codigos(state: StructuralState) -> set[StateIssueCode]:
    return {i.code for i in state.issues}


# ------------------------------------------------------- exaustividade --


class TestClassificacaoExaustiva:
    """§87, §88, §147 — todo tipo tem efeito declarado, e a lista é derivada."""

    def test_todo_tipo_de_evento_tem_efeito_declarado(self) -> None:
        for tipo in EventType:
            assert isinstance(structural_effect_of(tipo), StructuralEffect)

    def test_os_estruturais_sao_exatamente_tres(self) -> None:
        # SE ESTA LISTA CRESCER, o reducer precisa saber o que fazer com o tipo
        # novo — e este teste é o lugar onde a decisão aparece.
        assert {
            EventType.GOAL,
            EventType.SUBSTITUTION,
            EventType.CARD,
        } == STRUCTURAL_EVENT_TYPES

    @pytest.mark.parametrize(
        "tipo",
        [t for t in EventType if t not in (EventType.GOAL, EventType.SUBSTITUTION, EventType.CARD)],
    )
    def test_o_nao_estrutural_nao_move_o_estado(self, tipo: EventType) -> None:
        """§84 — ele continua sendo um fato, e não move ESTE estado."""
        antes = estado_inicial()
        depois = StateReducer().apply(
            antes, evento("nao-estrutural", tipo=tipo, minuto=10, time=CASA)
        )
        assert depois == antes


# --------------------------------------------------------------- gol --


class TestGol:
    def test_o_gol_da_casa_soma_no_lado_da_casa(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(), evento("g", tipo=EventType.GOAL, minuto=12, time=CASA)
        )
        assert (depois.score.home, depois.score.away) == (1, 0)

    def test_o_gol_de_fora_soma_no_lado_de_fora(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(), evento("g", tipo=EventType.GOAL, minuto=12, time=FORA)
        )
        assert (depois.score.home, depois.score.away) == (0, 1)

    def test_o_credito_e_do_time_do_evento_e_nao_do_time_do_jogador(self) -> None:
        """§15, §16 — o gol contra é creditado a quem MARCOU o ponto.

        O jogador é da casa e o crédito é de fora: é assim que o corpus
        descreve um gol contra, porque `EventType` não tem `OWN_GOAL`. Deduzir
        o lado pelo jogador inverteria o placar exatamente nesses lances.
        """
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "contra",
                tipo=EventType.GOAL,
                minuto=12,
                time=FORA,
                jogador_id=CASA_TITULARES[2],
            ),
        )
        assert (depois.score.home, depois.score.away) == (0, 1)

    def test_o_gol_da_prorrogacao_nao_entra_no_tempo_normal(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "et",
                tipo=EventType.GOAL,
                minuto=98,
                periodo=Period.EXTRA_TIME_FIRST,
                time=CASA,
            ),
        )
        assert depois.score.regular.home == 0
        assert depois.score.extra_time.home == 1
        assert depois.score.home == 1

    def test_a_disputa_de_penaltis_e_um_placar_separado(self) -> None:
        """§19, §98 — «2-1, 4-3 nos pênaltis» são dois resultados."""
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "pk",
                tipo=EventType.GOAL,
                minuto=0,
                periodo=Period.PENALTY_SHOOTOUT,
                time=CASA,
            ),
        )
        assert depois.score.shootout.home == 1
        assert depois.score.home == 0
        assert depois.score.regular.total == 0

    def test_gol_de_time_que_nao_joga_torna_o_placar_indisponivel(self) -> None:
        """§112 — fail-closed: somar num lado ao acaso seria pior."""
        intruso = TeamId.derive("pr052", "time-intruso")
        depois = StateReducer().apply(
            estado_inicial(), evento("g", tipo=EventType.GOAL, minuto=12, time=intruso)
        )
        assert not depois.score.is_available
        assert StateIssueCode.GOAL_TEAM_UNRESOLVED in codigos(depois)

    def test_o_placar_invalidado_nao_volta_a_contar(self) -> None:
        intruso = TeamId.derive("pr052", "time-intruso")
        reducer = StateReducer()
        estado = reducer.apply(
            estado_inicial(), evento("x", tipo=EventType.GOAL, minuto=12, time=intruso)
        )
        estado = reducer.apply(
            estado, evento("y", tipo=EventType.GOAL, minuto=20, time=CASA)
        )
        assert not estado.score.is_available
        assert estado.score.regular.total == 0


# ------------------------------------------------------- substituição --


class TestSubstituicao:
    def test_quem_sai_sai_e_quem_entra_entra(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "s",
                tipo=EventType.SUBSTITUTION,
                minuto=40,
                time=CASA,
                substituicao=(CASA_TITULARES[10], CASA_BANCO[0]),
            ),
        )
        em_campo = depois.on_field.team(CASA)
        assert em_campo is not None
        assert em_campo.size == 11
        assert not em_campo.has(CASA_TITULARES[10])
        assert em_campo.has(CASA_BANCO[0])
        assert depois.substitutions.count == 1

    def test_o_outro_time_nao_e_tocado(self) -> None:
        """§106 — a transição de um lado não diz nada sobre o outro."""
        antes = estado_inicial()
        depois = StateReducer().apply(
            antes,
            evento(
                "s",
                tipo=EventType.SUBSTITUTION,
                minuto=40,
                time=CASA,
                substituicao=(CASA_TITULARES[10], CASA_BANCO[0]),
            ),
        )
        assert depois.on_field.away == antes.on_field.away

    def test_quem_sai_sem_estar_em_campo_degrada_o_lado(self) -> None:
        """§31 — não repara: o campo daquele time deixa de ser afirmável."""
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "s",
                tipo=EventType.SUBSTITUTION,
                minuto=40,
                time=CASA,
                substituicao=(CASA_BANCO[1], CASA_BANCO[0]),
            ),
        )
        casa = depois.on_field.team(CASA)
        fora = depois.on_field.team(FORA)
        assert casa is not None
        assert not casa.is_available
        assert fora is not None
        assert fora.is_available
        assert StateIssueCode.SUBSTITUTION_PLAYER_NOT_ON_FIELD in codigos(depois)

    def test_quem_entra_ja_estando_em_campo_degrada_o_lado(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "s",
                tipo=EventType.SUBSTITUTION,
                minuto=40,
                time=CASA,
                substituicao=(CASA_TITULARES[10], CASA_TITULARES[0]),
            ),
        )
        assert StateIssueCode.SUBSTITUTION_PLAYER_ALREADY_ON_FIELD in codigos(depois)

    def test_substituicao_sem_detalhe_tipado_degrada_o_lado(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento("s", tipo=EventType.SUBSTITUTION, minuto=40, time=CASA),
        )
        assert StateIssueCode.SUBSTITUTION_WITHOUT_PLAYERS in codigos(depois)

    def test_a_substituicao_entra_no_historico_mesmo_sem_campo_afirmavel(self) -> None:
        """§33 — ela aconteceu; o que falta é a base para dizer quem está lá."""
        base = estado_inicial()
        degradado = OnFieldState(
            home=TeamOnFieldState(
                team_id=CASA,
                availability=FeatureAvailability.NOT_DECLARED,
                detail="escalação não publicada",
            ),
            away=base.on_field.away,
        )
        depois = StateReducer().apply(
            initial_structural_state(
                match_id=PARTIDA,
                home_team_id=CASA,
                away_team_id=FORA,
                score=ScoreState(),
                on_field=degradado,
                discipline=base.discipline,
            ),
            evento(
                "s",
                tipo=EventType.SUBSTITUTION,
                minuto=40,
                time=CASA,
                substituicao=(CASA_TITULARES[10], CASA_BANCO[0]),
            ),
        )
        assert depois.substitutions.count == 1
        casa = depois.on_field.team(CASA)
        assert casa is not None
        assert not casa.is_available


# ------------------------------------------------------------ cartão --


class TestCartao:
    def test_amarelo_conta_e_nao_tira_do_campo(self) -> None:
        """§36 — a única coisa que ele muda é a contagem."""
        antes = estado_inicial()
        depois = StateReducer().apply(
            antes,
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=25,
                time=CASA,
                jogador_id=CASA_TITULARES[3],
                cartao=CardType.YELLOW,
            ),
        )
        casa = depois.discipline.team(CASA)
        assert casa is not None
        assert (casa.yellow_cards, casa.dismissals) == (1, 0)
        assert depois.on_field == antes.on_field

    def test_vermelho_expulsa_e_tira_do_campo(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=58,
                time=FORA,
                jogador_id=FORA_TITULARES[4],
                cartao=CardType.RED,
            ),
        )
        disciplina = depois.discipline.team(FORA)
        em_campo = depois.on_field.team(FORA)
        assert disciplina is not None
        assert em_campo is not None
        assert (disciplina.yellow_cards, disciplina.dismissals) == (0, 1)
        assert disciplina.sent_off == (FORA_TITULARES[4],)
        assert em_campo.size == 10
        assert not em_campo.has(FORA_TITULARES[4])

    def test_segundo_amarelo_conta_como_amarelo_e_como_expulsao(self) -> None:
        """§38 — contá-lo só como expulsão faria a soma discordar da súmula."""
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=88,
                time=CASA,
                jogador_id=CASA_TITULARES[3],
                cartao=CardType.SECOND_YELLOW,
            ),
        )
        casa = depois.discipline.team(CASA)
        em_campo = depois.on_field.team(CASA)
        assert casa is not None
        assert em_campo is not None
        assert (casa.yellow_cards, casa.dismissals) == (1, 1)
        assert em_campo.size == 10

    def test_cartao_sem_detalhe_tipado_nao_conta_e_registra(self) -> None:
        """§39 — sem `CardDetail` não se sabe a COR, e cor é o dado.

        O modelo canônico já exige o executante de um cartão, então «expulsão
        sem jogador» não chega até aqui pelo corpus; o que chega é o cartão sem
        detalhe. Contá-lo como amarelo seria escolher a leitura mais barata.
        """
        antes = estado_inicial()
        depois = StateReducer().apply(
            antes,
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=58,
                time=FORA,
                jogador_id=FORA_TITULARES[4],
            ),
        )
        disciplina = depois.discipline.team(FORA)
        assert disciplina is not None
        assert (disciplina.yellow_cards, disciplina.dismissals) == (0, 0)
        assert depois.on_field == antes.on_field
        assert StateIssueCode.DISMISSAL_PLAYER_UNKNOWN in codigos(depois)

    def test_expulsao_de_quem_nao_esta_em_campo_degrada_o_lado(self) -> None:
        depois = StateReducer().apply(
            estado_inicial(),
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=58,
                time=FORA,
                jogador_id=FORA_BANCO[2],
                cartao=CardType.RED,
            ),
        )
        assert StateIssueCode.DISMISSAL_PLAYER_NOT_ON_FIELD in codigos(depois)

    def test_a_disciplina_do_outro_time_nao_muda(self) -> None:
        antes = estado_inicial()
        depois = StateReducer().apply(
            antes,
            evento(
                "c",
                tipo=EventType.CARD,
                minuto=25,
                time=CASA,
                jogador_id=CASA_TITULARES[3],
                cartao=CardType.YELLOW,
            ),
        )
        assert depois.discipline.away == antes.discipline.away


# ------------------------------------------------------------ guardas --


class TestGuardas:
    def test_evento_de_outra_partida_e_erro_e_nao_filtro(self) -> None:
        """§113 — um jogo plausível que não aconteceu é o pior resultado."""
        outra = MatchId.derive("pr052", "outra-partida")
        with pytest.raises(ValidationError, match="é da partida"):
            StateReducer().apply(
                estado_inicial(),
                evento("g", tipo=EventType.GOAL, minuto=12, match_id=outra),
            )

    def test_o_mesmo_problema_nao_se_repete_na_lista(self) -> None:
        """A lista é DIAGNÓSTICO, e não log.

        Um defeito estrutural — escalação ausente, por exemplo — apareceria uma
        vez por evento aplicado, e cem repetições da mesma linha esconderiam os
        outros problemas em vez de descrever este.
        """
        problema = StateIssue.degraded(
            StateIssueCode.LINEUP_UNAVAILABLE, "on_field", "sem escalação"
        )
        estado = estado_inicial().with_issue(problema).with_issue(problema)
        assert estado.issues == (problema,)
        assert problema.severity is StateIssueSeverity.DEGRADED

    def test_cada_defeito_de_evento_aparece_uma_vez_por_evento(self) -> None:
        """E o que é POR EVENTO continua sendo por evento.

        Três substituições sem detalhe são três defeitos, e não um: elas citam
        eventos diferentes, e fundi-las perderia quais foram.
        """
        reducer = StateReducer()
        estado = estado_inicial()
        for n in range(3):
            estado = reducer.apply(
                estado,
                evento(f"s{n}", tipo=EventType.SUBSTITUTION, minuto=40 + n, time=CASA),
            )
        repetidos = [
            i for i in estado.issues if i.code is StateIssueCode.SUBSTITUTION_WITHOUT_PLAYERS
        ]
        assert len(repetidos) == 3

    def test_apply_all_e_a_composicao_de_apply(self) -> None:
        eventos = (
            evento("a", tipo=EventType.GOAL, minuto=12, time=CASA),
            evento("b", tipo=EventType.GOAL, minuto=34, time=FORA),
        )
        reducer = StateReducer()
        um_a_um = reducer.apply(reducer.apply(estado_inicial(), eventos[0]), eventos[1])
        assert reducer.apply_all(estado_inicial(), eventos) == um_a_um
