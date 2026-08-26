"""Os componentes do estado — o que cada um recusa, e por quê.

O QUE ESTES TESTES PROVAM. Não são transições (isso é o reducer): são as
INVARIANTES que os tipos carregam sozinhos. Um `Tally` negativo, doze em campo,
o mesmo jogador nos dois times, uma cotação repetida no mesmo fluxo — cada um
desses é um estado que não existe no futebol, e o lugar de recusá-lo é o tipo,
não o chamador.

A DISTINÇÃO CENTRAL É `ObservedZero ≠ Unavailable` (§198). Ela aparece aqui
como duas coisas diferentes com a mesma aparência numérica: zero cartão
observado e zero cartão porque ninguém publicou evento. Os dois «valem 0» e não
significam a mesma coisa — e um consumidor que os confundisse aprenderia que
partidas sem cobertura são partidas disciplinadas.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.state.components import (
    MAX_EM_CAMPO,
    AppliedSubstitution,
    DisciplinaryState,
    EventStructuralState,
    OddsQuoteState,
    OddsState,
    OnFieldState,
    ScoreState,
    SubstitutionState,
    Tally,
    TeamDisciplinaryState,
    TeamOnFieldState,
    decimal_as_text,
)
from sports_intelligence.domain.features.temporal import MatchTimePoint
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import CASA, FORA, KICKOFF
from tests.support.state_fixtures import CASA_BANCO, CASA_TITULARES, FORA_TITULARES


class TestTally:
    def test_contagem_negativa_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="negativa"):
            Tally(home=-1)

    def test_somar_de_um_lado_nao_toca_o_outro(self) -> None:
        assert Tally(home=1, away=2).plus_home() == Tally(home=2, away=2)
        assert Tally(home=1, away=2).plus_away() == Tally(home=1, away=3)


class TestScoreState:
    def test_o_placar_soma_normal_e_prorrogacao_e_nunca_a_disputa(self) -> None:
        """§19 — «2-1, 4-3 nos pênaltis» são dois resultados, não 6-4."""
        placar = ScoreState(
            regular=Tally(home=2, away=1),
            extra_time=Tally(home=1, away=1),
            shootout=Tally(home=4, away=3),
        )
        assert (placar.home, placar.away) == (3, 2)
        assert placar.difference == 1
        assert placar.leader == "HOME"

    def test_o_empate_nao_tem_lider(self) -> None:
        placar = ScoreState(regular=Tally(home=1, away=1))
        assert placar.is_level
        assert placar.leader is None

    def test_o_placar_indisponivel_nao_tem_lider(self) -> None:
        """§14 — sem base para afirmar o placar, não há o que liderar."""
        placar = ScoreState(regular=Tally(home=2)).unavailable(
            FeatureAvailability.NOT_DECLARED, "sem EVENT"
        )
        assert not placar.is_available
        assert placar.leader is None

    def test_zero_a_zero_observado_difere_de_placar_indisponivel(self) -> None:
        """§198 — os dois «valem 0», e não são a mesma coisa."""
        observado = ScoreState()
        indisponivel = ScoreState().unavailable(
            FeatureAvailability.NOT_DECLARED, "a versão não publica EVENT"
        )
        assert (observado.home, indisponivel.home) == (0, 0)
        assert observado.is_available
        assert not indisponivel.is_available
        assert observado.as_canonical() != indisponivel.as_canonical()


class TestOnFieldState:
    def test_mais_de_onze_em_campo_e_recusado(self) -> None:
        """§27 — doze é conflito, e nunca uma lista para cortar."""
        with pytest.raises(ValidationError):
            TeamOnFieldState.of(CASA, (*CASA_TITULARES, *CASA_BANCO))

    def test_dez_em_campo_e_legitimo(self) -> None:
        """§28 — depois de uma expulsão, dez é o número certo."""
        assert TeamOnFieldState.of(CASA, CASA_TITULARES[:10]).size == 10

    def test_jogador_repetido_no_mesmo_time_e_recusado(self) -> None:
        with pytest.raises(ValidationError):
            TeamOnFieldState.of(CASA, (CASA_TITULARES[0], CASA_TITULARES[0]))

    def test_o_mesmo_jogador_nos_dois_times_e_recusado(self) -> None:
        """§26 — quase sempre resolução de identidade que fundiu dois jogadores."""
        with pytest.raises(ValidationError):
            OnFieldState(
                home=TeamOnFieldState.of(CASA, CASA_TITULARES),
                away=TeamOnFieldState.of(FORA, (CASA_TITULARES[0], *FORA_TITULARES[1:])),
            )

    def test_um_lado_indisponivel_nao_derruba_o_outro(self) -> None:
        """§106 — a degradação é do componente afetado, e só dele."""
        campo = OnFieldState(
            home=TeamOnFieldState.of(CASA, CASA_TITULARES),
            away=TeamOnFieldState(
                team_id=FORA,
                availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                detail="escalação ausente",
            ),
        )
        casa = campo.team(CASA)
        assert casa is not None
        assert casa.is_available
        assert not campo.is_available

    def test_time_que_nao_joga_a_partida_nao_tem_lado(self) -> None:
        campo = OnFieldState(
            home=TeamOnFieldState.of(CASA, CASA_TITULARES),
            away=TeamOnFieldState.of(FORA, FORA_TITULARES),
        )
        from sports_intelligence.domain.shared.identity import TeamId

        assert campo.team(TeamId.derive("pr052", "intruso")) is None

    def test_o_teto_e_onze(self) -> None:
        assert MAX_EM_CAMPO == 11


class TestDisciplinaryState:
    def test_o_amarelo_soma_sem_expulsar(self) -> None:
        time = TeamDisciplinaryState(team_id=CASA).plus_yellow()
        assert (time.yellow_cards, time.dismissals) == (1, 0)

    def test_a_expulsao_registra_quem_saiu(self) -> None:
        time = TeamDisciplinaryState(team_id=CASA).plus_dismissal(CASA_TITULARES[3])
        assert time.dismissals == 1
        assert time.sent_off == (CASA_TITULARES[3],)

    def test_zero_cartao_observado_difere_de_disciplina_nao_declarada(self) -> None:
        """§40, §198 — sem `EVENT` publicado, «zero cartões» não é observação."""
        observado = TeamDisciplinaryState(team_id=CASA)
        nao_declarado = TeamDisciplinaryState(
            team_id=CASA, availability=FeatureAvailability.NOT_DECLARED
        )
        assert observado.yellow_cards == nao_declarado.yellow_cards == 0
        assert observado.is_available
        assert not nao_declarado.is_available
        assert observado.as_canonical() != nao_declarado.as_canonical()

    def test_a_disciplina_de_um_lado_nao_e_a_do_outro(self) -> None:
        estado = DisciplinaryState(
            home=TeamDisciplinaryState(team_id=CASA).plus_yellow(),
            away=TeamDisciplinaryState(team_id=FORA),
        )
        casa, fora = estado.team(CASA), estado.team(FORA)
        assert casa is not None
        assert fora is not None
        assert (casa.yellow_cards, fora.yellow_cards) == (1, 0)


class TestSubstitutionState:
    def test_as_substituicoes_ficam_na_ordem_em_que_entraram(self) -> None:
        estado = SubstitutionState()
        for n in range(3):
            estado = estado.plus(
                AppliedSubstitution(
                    event_id=uuid.uuid5(uuid.NAMESPACE_OID, f"s{n}"),
                    team_id=CASA,
                    player_out=CASA_TITULARES[n],
                    player_in=CASA_BANCO[n],
                    at=MatchTimePoint.of(Period.SECOND_HALF, 60 + n),
                )
            )
        assert estado.count == 3
        assert [s.player_in for s in estado.by_team(CASA)] == list(CASA_BANCO)
        assert estado.by_team(FORA) == ()


class TestOddsState:
    def _cotacao(self, valor: str, *, selecao: str = "HOME") -> OddsQuoteState:
        return OddsQuoteState(
            bookmaker="BET365",
            market="MATCH_RESULT_1X2",
            selection=selecao,
            decimal_odds=decimal_as_text(Decimal(valor)),
            observed_at=KICKOFF,
        )

    def test_duas_cotacoes_do_mesmo_fluxo_sao_recusadas(self) -> None:
        """§122 — o estado guarda a ÚLTIMA de cada fluxo, e não uma pilha."""
        with pytest.raises(ValidationError):
            OddsState.of((self._cotacao("1.80"), self._cotacao("1.85")))

    def test_selecoes_diferentes_sao_fluxos_diferentes(self) -> None:
        estado = OddsState.of((self._cotacao("1.80"), self._cotacao("4.20", selecao="AWAY")))
        assert estado.count == 2
        assert estado.bookmakers == ("BET365",)

    def test_a_linha_faz_parte_do_fluxo(self) -> None:
        """Over 2.5 e Over 3.5 são mercados diferentes, e não uma revisão."""
        base = self._cotacao("1.90")
        from dataclasses import replace

        estado = OddsState.of((replace(base, line="2.5"), replace(base, line="3.5")))
        assert estado.count == 2

    def test_sem_cotacao_nao_e_o_mesmo_que_cotacao_indisponivel(self) -> None:
        vazio = OddsState()
        indisponivel = OddsState(
            availability=FeatureAvailability.TEMPORALLY_UNAVAILABLE,
            detail="nenhuma elegível neste corte",
        )
        assert vazio.count == indisponivel.count == 0
        assert vazio.is_available
        assert not indisponivel.is_available


class TestEventStructuralState:
    def test_o_digest_vazio_descreve_ausencia_de_evento(self) -> None:
        estado = EventStructuralState()
        assert estado.effective_count == 0
        assert estado.digest == ""
        assert estado.is_available

    def test_a_ausencia_declarada_nao_e_contagem_zero(self) -> None:
        nao_declarado = EventStructuralState(availability=FeatureAvailability.NOT_DECLARED)
        assert nao_declarado.effective_count == 0
        assert not nao_declarado.is_available


class TestDecimalAsText:
    def test_o_texto_e_estavel_para_o_mesmo_numero(self) -> None:
        """A impressão do estado depende dele: `1.80` e `1.8` são o mesmo valor."""
        assert decimal_as_text(Decimal("1.80")) == decimal_as_text(Decimal("1.8"))
