"""Partida, placar e escalação — com os invariantes que pegam fusão errada."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sports_intelligence.domain.competitions.catalog import CompetitionCode
from sports_intelligence.domain.competitions.models import (
    Competition,
    CompetitionRegime,
    RegimeCode,
    Season,
    Stage,
    StageType,
)
from sports_intelligence.domain.matches.lifecycle import MatchLifecycle
from sports_intelligence.domain.matches.lineup import (
    STARTERS,
    FormationLabel,
    Lineup,
    LineupEntry,
    LineupStatus,
    assert_squads_are_disjoint,
)
from sports_intelligence.domain.matches.models import (
    Match,
    MatchIdentityCandidate,
    Venue,
)
from sports_intelligence.domain.matches.result import MatchResult, Outcome, Score
from sports_intelligence.domain.shared.identity import MatchId, PlayerId, TeamId
from sports_intelligence.domain.shared.temporal import instant

REGIME = CompetitionRegime(
    code=RegimeCode.DOUBLE_ROUND_ROBIN,
    effective_from=instant(datetime(2020, 1, 1, tzinfo=UTC)),
    regulation_version="2024/25",
)
KICKOFF = instant(datetime(2025, 3, 8, 17, 30, tzinfo=UTC))
COMPETICAO = Competition.from_code(CompetitionCode.PREMIER_LEAGUE)
TEMPORADA = Season.create(
    competition_id=COMPETICAO.id,
    label="2024-2025",
    starts_at=instant(datetime(2024, 8, 1, tzinfo=UTC)),
    ends_at=instant(datetime(2025, 5, 31, tzinfo=UTC)),
    regime=REGIME,
)


def _match(**mudancas: object) -> Match:
    campos: dict[str, object] = {
        "competition_id": COMPETICAO.id,
        "season_id": TEMPORADA.id,
        "regime": REGIME,
        "stage": Stage(type=StageType.LEAGUE, round_number=28),
        "home_team_id": TeamId.new(),
        "away_team_id": TeamId.new(),
        "scheduled_kickoff": KICKOFF,
    }
    campos.update(mudancas)
    return Match.register(**campos)  # type: ignore[arg-type]


class TestMatch:
    def test_nasce_descoberta(self) -> None:
        """Alguma fonte disse que existe. Confirmar é transição, não um
        construtor diferente."""
        assert _match().lifecycle is MatchLifecycle.DISCOVERED

    def test_mandante_e_visitante_nao_podem_ser_o_mesmo(self) -> None:
        """Quase sempre resolução de identidade que fundiu dois clubes."""
        time = TeamId.new()
        with pytest.raises(ValueError, match="mesmo time"):
            _match(home_team_id=time, away_team_id=time)

    def test_o_regime_precisa_cobrir_o_pontape(self) -> None:
        """Uma partida fora do regime aconteceu sob outro formato."""
        encerrado = CompetitionRegime(
            code=RegimeCode.DOUBLE_ROUND_ROBIN,
            effective_from=instant(datetime(2000, 1, 1, tzinfo=UTC)),
            effective_to=instant(datetime(2010, 1, 1, tzinfo=UTC)),
            regulation_version="antigo",
        )
        with pytest.raises(ValueError, match="não cobre"):
            _match(regime=encerrado)

    def test_a_partida_nao_carrega_o_resultado(self) -> None:
        """A DECISÃO MAIS IMPORTANTE DO MÓDULO. Se o agregado carregasse o
        placar, qualquer caminho que descreva o minuto 63 poderia lê-lo — e a
        descrição passaria a conter a resposta (ADR-0007)."""
        partida = _match()
        for atributo in ("result", "score", "final_score", "outcome", "goals"):
            assert not hasattr(partida, atributo), atributo

    def test_ids_sao_sorteados_e_nao_derivados_do_confronto(self) -> None:
        """Duas partidas do mesmo par no mesmo dia existem em torneios."""
        campos = {"home_team_id": TeamId.new(), "away_team_id": TeamId.new()}
        assert _match(**campos).id != _match(**campos).id

    def test_kickoff_prefere_o_real(self) -> None:
        real = instant(datetime(2025, 3, 8, 17, 45, tzinfo=UTC))
        assert _match().kickoff == KICKOFF
        assert _match().with_actual_kickoff(real).kickoff == real

    def test_opponent_of(self) -> None:
        partida = _match()
        assert partida.opponent_of(partida.home_team_id) == partida.away_team_id
        with pytest.raises(ValueError, match="não joga"):
            partida.opponent_of(TeamId.new())

    def test_venue_valida_o_pais(self) -> None:
        Venue(name="Emirates", city="Londres", country="GB")
        with pytest.raises(ValueError, match="country"):
            Venue(name="X", country="GBR")


class TestMatchIdentityCandidate:
    def test_nao_produz_merge(self) -> None:
        """A AUSÊNCIA É O CONTRATO. Um `matches()` aqui convidaria a fundir
        por semelhança — e é assim que duas partidas viram uma."""
        candidato = MatchIdentityCandidate.of(_match())
        for metodo in ("matches", "merge_with", "similarity_to", "resolve"):
            assert not hasattr(candidato, metodo), metodo

    def test_descreve_os_elementos_de_identificacao(self) -> None:
        partida = _match()
        candidato = MatchIdentityCandidate.of(partida)
        assert candidato.home_team_id == partida.home_team_id
        assert candidato.kickoff == partida.kickoff
        assert candidato.stage == partida.stage


class TestScore:
    def test_desfecho_e_derivado_nunca_informado(self) -> None:
        """Um campo `outcome` preenchido pela fonte pode discordar do placar
        da mesma fonte — e aí há duas verdades."""
        assert Score(home=2, away=1).outcome is Outcome.HOME
        assert Score(home=1, away=1).outcome is Outcome.DRAW
        assert Score(home=0, away=3).outcome is Outcome.AWAY

    def test_placar_negativo_e_implausivel_sao_recusados(self) -> None:
        with pytest.raises(ValueError, match="negativo"):
            Score(home=-1, away=0)
        with pytest.raises(ValueError, match="implausível"):
            Score(home=99, away=0)


class TestMatchResult:
    def test_o_caso_comum_decidido_em_90(self) -> None:
        resultado = MatchResult.in_regular_time(2, 1)
        assert resultado.outcome is Outcome.HOME
        assert not resultado.went_to_extra_time
        assert resultado.decided_in_regular_time

    def test_penaltis_nao_falsificam_o_placar_de_gols(self) -> None:
        """O INVARIANTE CENTRAL. Somar pênaltis a gols infla o ataque de todo
        clube que foi a decisões."""
        resultado = MatchResult(
            regular_time=Score(home=1, away=1),
            penalties=Score(home=4, away=2),
        )
        assert resultado.goals == Score(home=1, away=1)
        assert resultado.goals.total == 2
        assert resultado.outcome is Outcome.HOME
        assert resultado.goals.outcome is Outcome.DRAW

    def test_prorrogacao_e_acumulada(self) -> None:
        resultado = MatchResult(
            regular_time=Score(home=1, away=1), extra_time=Score(home=2, away=1)
        )
        assert resultado.goals.total == 3
        assert resultado.outcome is Outcome.HOME

    def test_prorrogacao_com_menos_gols_e_coluna_trocada(self) -> None:
        with pytest.raises(ValueError, match="acumulado"):
            MatchResult(regular_time=Score(home=2, away=1), extra_time=Score(home=1, away=1))

    def test_prorrogacao_so_existe_apos_empate(self) -> None:
        with pytest.raises(ValueError, match="tempo normal"):
            MatchResult(regular_time=Score(home=2, away=1), extra_time=Score(home=3, away=1))

    def test_penaltis_so_decidem_empate(self) -> None:
        with pytest.raises(ValueError, match="só decidem empate"):
            MatchResult(regular_time=Score(home=2, away=1), penalties=Score(home=4, away=2))

    def test_penaltis_empatados_nao_decidem_nada(self) -> None:
        with pytest.raises(ValueError, match="existe para decidir"):
            MatchResult(regular_time=Score(home=1, away=1), penalties=Score(home=3, away=3))


def _entry(status: LineupStatus = LineupStatus.STARTER, **campos: object) -> LineupEntry:
    base: dict[str, object] = {"player_id": PlayerId.new(), "status": status}
    base.update(campos)
    return LineupEntry(**base)  # type: ignore[arg-type]


def _lineup(entries: tuple[LineupEntry, ...], **campos: object) -> Lineup:
    base: dict[str, object] = {
        "match_id": MatchId.new(),
        "team_id": TeamId.new(),
        "entries": entries,
    }
    base.update(campos)
    return Lineup(**base)  # type: ignore[arg-type]


class TestFormationLabel:
    @pytest.mark.parametrize("rotulo", ["4-3-3", "4-2-3-1", "3-5-2", "3-4-2-1"])
    def test_aceita_as_formacoes_reais(self, rotulo: str) -> None:
        assert str(FormationLabel(rotulo)) == rotulo

    def test_o_goleiro_nao_entra_no_rotulo(self) -> None:
        """`4-3-3` são dez jogadores de linha. Uma soma de 11 quer dizer que
        alguém incluiu o goleiro, e aí o rótulo descreve outro desenho."""
        with pytest.raises(ValueError, match="goleiro não entra"):
            FormationLabel("1-4-3-3")

    @pytest.mark.parametrize("rotulo", ["433", "4:3:3", "4-3-4", ""])
    def test_recusa_o_que_nao_e_formacao(self, rotulo: str) -> None:
        with pytest.raises(ValueError, match="formação"):
            FormationLabel(rotulo)

    def test_lines(self) -> None:
        assert FormationLabel("4-2-3-1").lines == (4, 2, 3, 1)


class TestLineup:
    def test_onze_titulares_no_maximo(self) -> None:
        entradas = tuple(_entry() for _ in range(STARTERS + 1))
        with pytest.raises(ValueError, match="titulares"):
            _lineup(entradas)

    def test_escalacao_parcial_e_legitima(self) -> None:
        """É o que se sabe na janela pré-jogo, antes de a oficial sair."""
        parcial = _lineup(tuple(_entry() for _ in range(7)))
        assert not parcial.is_complete

    def test_jogador_duplicado_e_recusado(self) -> None:
        """Sintoma clássico de duas fontes fundidas sem deduplicação."""
        jogador = PlayerId.new()
        with pytest.raises(ValueError, match="duas vezes"):
            _lineup(
                (
                    _entry(player_id=jogador),
                    _entry(player_id=jogador, status=LineupStatus.BENCH),
                )
            )

    def test_capitao_precisa_ser_titular(self) -> None:
        with pytest.raises(ValueError, match="capitão"):
            _entry(status=LineupStatus.BENCH, captain=True)

    def test_so_um_capitao(self) -> None:
        with pytest.raises(ValueError, match="capitães"):
            _lineup((_entry(captain=True), _entry(captain=True)))

    def test_o_capitao_pertence_a_escalacao(self) -> None:
        entrada = _entry(captain=True)
        escalacao = _lineup((entrada, _entry()))
        capitao = escalacao.captain
        assert capitao is not None
        assert capitao.player_id in escalacao.player_ids

    def test_numero_ausente_nao_e_zero(self) -> None:
        """Constituição §4: número ausente é `None`, nunca 0."""
        assert _entry().shirt_number is None
        with pytest.raises(ValueError, match=r"fora de 1\.\.99"):
            _entry(shirt_number=0)

    def test_numeros_repetidos_sao_recusados(self) -> None:
        with pytest.raises(ValueError, match="mesmo número"):
            _lineup((_entry(shirt_number=10), _entry(shirt_number=10)))

    def test_a_formacao_nao_e_inferida_da_contagem(self) -> None:
        """Contar posições e concluir 4-3-3 erra: um 4-2-3-1 e um 4-5-1 têm a
        mesma contagem por linha e são desenhos diferentes."""
        escalacao = _lineup(tuple(_entry() for _ in range(STARTERS)))
        assert escalacao.formation is None
        assert escalacao.is_complete


class TestIsolamentoEntreEscalacoes:
    def test_jogador_nos_dois_times_e_recusado(self) -> None:
        """O ERRO MAIS CARO DA FUSÃO DE FONTES. Quando a resolução funde dois
        homônimos de times adversários, ele aparece dos dois lados e toda
        estatística por jogador daquela partida conta duas vezes."""
        match_id = MatchId.new()
        comum = PlayerId.new()
        casa = _lineup((_entry(player_id=comum), _entry()), match_id=match_id)
        fora = _lineup((_entry(player_id=comum), _entry()), match_id=match_id)
        with pytest.raises(ValueError, match="nos dois times"):
            assert_squads_are_disjoint(casa, fora)

    def test_escalacoes_de_partidas_diferentes_sao_recusadas(self) -> None:
        """Comparar escalações de partidas distintas passaria trivialmente."""
        with pytest.raises(ValueError, match="partidas diferentes"):
            assert_squads_are_disjoint(_lineup((_entry(),)), _lineup((_entry(),)))

    def test_escalacoes_do_mesmo_time_sao_recusadas(self) -> None:
        match_id, team_id = MatchId.new(), TeamId.new()
        a = _lineup((_entry(),), match_id=match_id, team_id=team_id)
        b = _lineup((_entry(),), match_id=match_id, team_id=team_id)
        with pytest.raises(ValueError, match="mesmo time"):
            assert_squads_are_disjoint(a, b)

    def test_escalacoes_disjuntas_passam(self) -> None:
        match_id = MatchId.new()
        casa = _lineup((_entry(), _entry()), match_id=match_id)
        fora = _lineup((_entry(), _entry()), match_id=match_id)
        assert_squads_are_disjoint(casa, fora)
