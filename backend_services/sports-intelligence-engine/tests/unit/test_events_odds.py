"""Coordenadas, taxonomia, revisão de eventos e o domínio de odds."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from sports_intelligence.domain.events.canonical import (
    CanonicalMatchEvent,
    EventStatus,
    current_truth,
)
from sports_intelligence.domain.events.coordinates import (
    OPPONENT_GOAL,
    CoordinateFrame,
    PitchCoordinate,
)
from sports_intelligence.domain.events.details import (
    BodyPart,
    CardDetail,
    CardType,
    PassDetail,
    PassOutcome,
    ShotDetail,
    ShotOutcome,
    SubstitutionDetail,
)
from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.odds.models import (
    BookmakerRef,
    OddsMarket,
    OddsQuote,
    OddsSelection,
)
from sports_intelligence.domain.shared.feature_value import FeatureValue, Unavailability
from sports_intelligence.domain.shared.identity import (
    MatchId,
    PlayerId,
    ProviderId,
    TeamId,
)
from sports_intelligence.domain.shared.provenance import (
    DataProvenance,
    SourceType,
)
from sports_intelligence.domain.shared.quality import DataQuality
from sports_intelligence.domain.shared.temporal import (
    MatchClock,
    ObservationTimes,
    Period,
    instant,
)

AGORA = instant(datetime(2025, 3, 8, 18, 3, tzinfo=UTC))
PROV = DataProvenance(
    source_type=SourceType.COMMERCIAL_PROVIDER,
    provider_id=ProviderId("provedor_a"),
    source_record_id="ev-1",
    times=ObservationTimes.at_once(AGORA),
)
QUAL = DataQuality.perfect()
CLOCK = MatchClock(Period.SECOND_HALF, 63)


class TestCoordenadas:
    def test_o_referencial_e_declarado(self) -> None:
        """Provedores discordam sobre a origem. Um chute a 5 metros do gol
        vira um chute do próprio campo dependendo de quem descreveu."""
        ponto = PitchCoordinate(x=0.95, y=0.5)
        assert ponto.frame is CoordinateFrame.ATTACKING

    def test_fora_do_intervalo_e_recusado(self) -> None:
        for x, y in ((1.5, 0.5), (-0.1, 0.5), (0.5, 2.0)):
            with pytest.raises(ValueError, match=r"\[0,1\]"):
                PitchCoordinate(x=x, y=y)

    def test_referenciais_diferentes_nao_se_comparam(self) -> None:
        """A distância entre um ponto ATTACKING e um ABSOLUTE é calculável e
        sem sentido — e o número não denuncia nada."""
        atacando = PitchCoordinate(x=0.9, y=0.5)
        absoluto = PitchCoordinate(x=0.9, y=0.5, frame=CoordinateFrame.ABSOLUTE)
        with pytest.raises(ValueError, match="referenciais diferentes"):
            atacando.distance_to(absoluto)

    def test_perto_do_gol_e_sempre_x_alto(self) -> None:
        """O motivo de o referencial ser o de ataque: um chute perigoso é
        `x ≈ 0.95` no primeiro tempo, no segundo, para mandante e visitante."""
        assert PitchCoordinate(x=0.95, y=0.5).distance_to_opponent_goal < 0.1
        assert PitchCoordinate(x=0.1, y=0.5).distance_to_opponent_goal > 0.8

    def test_distancia_ao_gol_exige_o_referencial_de_ataque(self) -> None:
        """Em ABSOLUTE não existe 'gol adversário' — o referencial não sabe
        quem ataca para onde."""
        absoluto = PitchCoordinate(x=0.9, y=0.5, frame=CoordinateFrame.ABSOLUTE)
        with pytest.raises(ValueError, match="ATTACKING"):
            _ = absoluto.distance_to_opponent_goal

    def test_flip_espelha_os_dois_eixos(self) -> None:
        """Virar o campo inverte também a lateral."""
        assert PitchCoordinate(x=0.8, y=0.7) == PitchCoordinate(x=0.2, y=0.3).flip()

    def test_o_gol_adversario_e_constante_nomeada(self) -> None:
        assert PitchCoordinate(x=1.0, y=0.5) == OPPONENT_GOAL


class TestTaxonomia:
    def test_evento_estrutural_nao_pertence_a_time(self) -> None:
        """O apito final não é do mandante. Inventar um dono distorce toda
        contagem por equipe."""
        assert not EventType.MATCH_END.requires_team
        with pytest.raises(ValueError, match="não pertence a nenhum time"):
            CanonicalMatchEvent.record(
                match_id=MatchId.new(),
                type=EventType.MATCH_END,
                clock=MatchClock(Period.FULL_TIME, 0),
                sequence=0,
                provenance=PROV,
                quality=QUAL,
                team_id=TeamId.new(),
            )

    def test_evento_de_acao_exige_time(self) -> None:
        with pytest.raises(ValueError, match="sem team_id"):
            CanonicalMatchEvent.record(
                match_id=MatchId.new(),
                type=EventType.SHOT,
                clock=CLOCK,
                sequence=1,
                provenance=PROV,
                quality=QUAL,
                player_id=PlayerId.new(),
            )

    def test_evento_com_executante_exige_jogador(self) -> None:
        with pytest.raises(ValueError, match="executante"):
            CanonicalMatchEvent.record(
                match_id=MatchId.new(),
                type=EventType.PASS,
                clock=CLOCK,
                sequence=1,
                provenance=PROV,
                quality=QUAL,
                team_id=TeamId.new(),
            )

    def test_pressure_nao_exige_executante(self) -> None:
        """Pressão às vezes é coletiva."""
        assert not EventType.PRESSURE.requires_player

    def test_classificacoes(self) -> None:
        assert EventType.CORNER.is_set_piece
        assert EventType.VAR.is_stoppage
        assert EventType.PERIOD_START.is_structural


def _evento(**campos: object) -> CanonicalMatchEvent:
    base: dict[str, object] = {
        "match_id": MatchId.new(),
        "type": EventType.SHOT,
        "clock": CLOCK,
        "sequence": 12,
        "provenance": PROV,
        "quality": QUAL,
        "team_id": TeamId.new(),
        "player_id": PlayerId.new(),
    }
    base.update(campos)
    return CanonicalMatchEvent.record(**base)  # type: ignore[arg-type]


class TestRevisaoDeEventos:
    def test_correcao_nao_apaga_o_anterior(self) -> None:
        """Se a correção sobrescrevesse, 'o que sabíamos no minuto 63'
        ficaria sem resposta — e o replay enxergaria o futuro."""
        original = _evento()
        anterior, nova = original.correct_to(
            provenance=PROV, quality=QUAL, player_id=PlayerId.new()
        )
        assert anterior.id == original.id
        assert anterior.status is EventStatus.CORRECTED
        assert nova.revision == 2
        assert nova.supersedes == original.id
        assert nova.status is EventStatus.ACTIVE

    def test_cancelamento_e_diferente_de_correcao(self) -> None:
        """Um gol anulado pelo VAR não é um gol corrigido."""
        cancelado = _evento().cancel()
        assert cancelado.status is EventStatus.CANCELLED
        assert not cancelado.is_current_truth

    def test_evento_cancelado_nao_se_corrige(self) -> None:
        with pytest.raises(ValueError, match="não se corrige"):
            _evento().cancel().correct_to(provenance=PROV, quality=QUAL)

    def test_cancelar_duas_vezes_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="já cancelado"):
            _evento().cancel().cancel()

    def test_revisao_sem_predecessor_quebra_a_cadeia(self) -> None:
        import uuid

        with pytest.raises(ValueError, match="cadeia de correção"):
            CanonicalMatchEvent(
                id=uuid.uuid4(),
                match_id=MatchId.new(),
                type=EventType.SHOT,
                clock=CLOCK,
                sequence=1,
                provenance=PROV,
                quality=QUAL,
                team_id=TeamId.new(),
                player_id=PlayerId.new(),
                revision=2,
            )

    def test_a_verdade_atual_ignora_corrigidos_e_cancelados(self) -> None:
        match_id = MatchId.new()
        original = _evento(match_id=match_id, sequence=1)
        anterior, nova = original.correct_to(provenance=PROV, quality=QUAL)
        cancelado = _evento(match_id=match_id, sequence=2).cancel()
        ativo = _evento(match_id=match_id, sequence=3)

        verdade = current_truth((anterior, nova, cancelado, ativo))
        assert {e.id for e in verdade} == {nova.id, ativo.id}

    def test_a_ordem_e_explicita_e_nao_a_de_chegada(self) -> None:
        """Provedores entregam fora de ordem, e ordenação implícita muda
        entre execuções (Constituição §9)."""
        match_id = MatchId.new()
        tarde = _evento(match_id=match_id, clock=MatchClock(Period.SECOND_HALF, 80), sequence=2)
        cedo = _evento(match_id=match_id, clock=MatchClock(Period.FIRST_HALF, 10), sequence=1)
        assert [e.id for e in current_truth((tarde, cedo))] == [cedo.id, tarde.id]


class TestDetalhesTipados:
    def test_xg_ausente_nao_e_xg_zero(self) -> None:
        """Constituição §4. Zero significaria 'chance nula', que é uma
        afirmação sobre algo não medido — e entraria em qualquer média."""
        ausente = ShotDetail(
            outcome=ShotOutcome.SAVED,
            xg=FeatureValue.absent(Unavailability.NOT_PUBLISHED),
        )
        assert ausente.xg is not None
        assert not ausente.xg.is_available
        zero = ShotDetail(outcome=ShotOutcome.SAVED, xg=FeatureValue.of(0.0))
        assert zero.xg is not None
        assert zero.xg.is_available

    def test_xg_fora_de_zero_um_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="probabilidade"):
            ShotDetail(outcome=ShotOutcome.GOAL, xg=FeatureValue.of(1.4))

    def test_trave_nao_conta_como_no_alvo(self) -> None:
        """Convenção estatística: a trave não exigiu defesa."""
        assert ShotDetail(outcome=ShotOutcome.GOAL).on_target
        assert ShotDetail(outcome=ShotOutcome.SAVED).on_target
        assert not ShotDetail(outcome=ShotOutcome.POST).on_target
        assert not ShotDetail(outcome=ShotOutcome.BLOCKED).on_target

    def test_passe_incompleto_nao_tem_destinatario(self) -> None:
        """Aceitar os dois faria 'passes recebidos' contar o que não chegou."""
        with pytest.raises(ValueError, match="passe completo"):
            PassDetail(outcome=PassOutcome.INCOMPLETE, recipient_id=PlayerId.new())

    def test_passe_completo_pode_ter_destinatario(self) -> None:
        PassDetail(
            outcome=PassOutcome.COMPLETE,
            recipient_id=PlayerId.new(),
            body_part=BodyPart.RIGHT_FOOT,
        )

    def test_segundo_amarelo_e_distinguivel_de_vermelho(self) -> None:
        """As duas expulsões descrevem situações diferentes: acúmulo de
        faltas táticas contra um lance grave isolado."""
        # Membros distintos do enum: uma expulsão por acúmulo não é
        # indistinguível de um vermelho direto.
        assert len({CardType.SECOND_YELLOW, CardType.RED, CardType.YELLOW}) == 3
        assert CardType.SECOND_YELLOW.is_dismissal
        assert CardType.RED.is_dismissal
        assert not CardType.YELLOW.is_dismissal
        CardDetail(card_type=CardType.SECOND_YELLOW, reason="falta tática")

    def test_substituicao_exige_jogadores_diferentes(self) -> None:
        jogador = PlayerId.new()
        with pytest.raises(ValueError, match="a si mesmo"):
            SubstitutionDetail(player_out=jogador, player_in=jogador)

    def test_substituicao_valida(self) -> None:
        detalhe = SubstitutionDetail(player_out=PlayerId.new(), player_in=PlayerId.new())
        evento = _evento(type=EventType.SUBSTITUTION, detail=detalhe, player_id=None)
        assert evento.detail is detalhe


class TestOdds:
    def _quote(self, **campos: object) -> OddsQuote:
        base: dict[str, object] = {
            "match_id": MatchId.new(),
            "bookmaker": BookmakerRef("pinnacle"),
            "market": OddsMarket.MATCH_RESULT_1X2,
            "selection": OddsSelection.HOME,
            "decimal_odds": "1.95",
            "observed_at": AGORA,
            "provenance": PROV,
        }
        base.update(campos)
        return OddsQuote.observe(**base)  # type: ignore[arg-type]

    def test_cotacao_precisa_ser_maior_que_um(self) -> None:
        """Uma cotação decimal inclui o valor apostado; 1,00 seria devolver
        o dinheiro."""
        with pytest.raises(ValueError, match="deve ser > 1"):
            self._quote(decimal_odds="1.0")

    def test_decimal_e_nao_float(self) -> None:
        """`Decimal("1.95")` não carrega o erro de representação que
        `Decimal(1.95)` a partir de float carregaria."""
        assert self._quote().decimal_odds == Decimal("1.95")

    def test_selecao_precisa_existir_no_mercado(self) -> None:
        """`TOTAL_GOALS` com seleção `DRAW` produziria uma série que ninguém
        sabe ler."""
        with pytest.raises(ValueError, match="não existe no mercado"):
            self._quote(market=OddsMarket.TOTAL_GOALS, selection=OddsSelection.DRAW, line="2.5")

    def test_mercado_com_linha_exige_a_linha(self) -> None:
        """'Mais de 2,5' e 'mais de 3,5' são apostas diferentes com a mesma
        seleção."""
        with pytest.raises(ValueError, match="exige linha"):
            self._quote(market=OddsMarket.TOTAL_GOALS, selection=OddsSelection.OVER)

    def test_mercado_sem_linha_recusa_linha(self) -> None:
        with pytest.raises(ValueError, match="não tem linha"):
            self._quote(line="2.5")

    def test_a_observacao_carrega_o_instante(self) -> None:
        """Sem `current_odds`: a diferença entre abertura e fechamento é o
        sinal, e um campo 'atual' a apagaria."""
        quote = self._quote()
        assert quote.observed_at == AGORA
        assert not hasattr(quote, "current_odds")

    def test_suspenso_e_informacao_nao_ausencia(self) -> None:
        """Uma casa suspende quando algo aconteceu — descartar apaga o
        momento mais informativo."""
        assert self._quote(suspended=True).suspended

    def test_a_procedencia_e_preservada(self) -> None:
        assert self._quote().provenance.provider_id == ProviderId("provedor_a")

    def test_bookmaker_e_slug(self) -> None:
        assert str(BookmakerRef(" Pinnacle ")) == "pinnacle"
        with pytest.raises(ValueError, match="BookmakerRef"):
            BookmakerRef("bet-365")

    def test_a_serie_e_identificada_por_casa_mercado_e_linha(self) -> None:
        """As seleções de um mercado são lados da mesma cotação e se movem
        juntas."""
        over = self._quote(
            market=OddsMarket.TOTAL_GOALS, selection=OddsSelection.OVER, line="2.5"
        )
        under = self._quote(
            market=OddsMarket.TOTAL_GOALS, selection=OddsSelection.UNDER, line="2.5"
        )
        assert over.market_key == under.market_key

    def test_nada_de_calculo_derivado(self) -> None:
        """Probabilidade implícita, overround e consenso são interpretação
        versionada — pertencem ao Odds Intelligence."""
        quote = self._quote()
        for atributo in ("implied_probability", "overround", "consensus", "velocity"):
            assert not hasattr(quote, atributo), atributo
