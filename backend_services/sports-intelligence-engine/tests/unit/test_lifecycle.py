"""O ciclo de vida, e o invariante que impede uma partida de se descrever."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

import pytest

from sports_intelligence.domain.matches.lifecycle import (
    IllegalTransitionError,
    MatchLifecycle,
    allowed_transitions,
    assert_can_feed_historical_index,
    can_transition,
    transition_to,
)
from sports_intelligence.domain.shared.errors import InvariantViolationError
from sports_intelligence.domain.shared.temporal import instant

AGORA = instant(datetime(2026, 8, 12, 15, 0, tzinfo=UTC))


class TestOCicloNormal:
    def test_o_caminho_completo_e_percorrivel(self) -> None:
        """O princípio central do motor: toda partida ao vivo é também um
        dataset histórico futuro."""
        caminho = [
            MatchLifecycle.DISCOVERED,
            MatchLifecycle.SCHEDULED,
            MatchLifecycle.PRE_MATCH,
            MatchLifecycle.LIVE,
            MatchLifecycle.FINISHED_PENDING_RECONCILIATION,
            MatchLifecycle.RECONCILED,
            MatchLifecycle.HISTORICAL_PENDING_BUILD,
            MatchLifecycle.HISTORICAL_ACTIVE,
        ]
        for atual, seguinte in pairwise(caminho):
            assert can_transition(atual, seguinte), f"{atual} -> {seguinte}"

    def test_toda_transicao_registra_o_motivo(self) -> None:
        """ "Por que esta partida virou DATA_INVALID às 03:14?" é a primeira
        pergunta de todo incidente."""
        t = transition_to(
            MatchLifecycle.LIVE,
            MatchLifecycle.FINISHED_PENDING_RECONCILIATION,
            at=AGORA,
            reason="apito final recebido do provedor",
        )
        assert t.reason == "apito final recebido do provedor"
        assert t.at == AGORA

    def test_motivo_vazio_e_recusado(self) -> None:
        with pytest.raises(ValueError, match="motivo"):
            transition_to(MatchLifecycle.SCHEDULED, MatchLifecycle.PRE_MATCH, at=AGORA, reason="  ")


class TestTransicoesProibidas:
    def test_nao_se_pula_etapa(self) -> None:
        """Ir de agendada direto para ao vivo pula a janela pré-jogo, onde o
        contexto e o mercado são coletados."""
        with pytest.raises(IllegalTransitionError):
            transition_to(MatchLifecycle.SCHEDULED, MatchLifecycle.LIVE, at=AGORA, reason="x")

    def test_cancelada_nao_volta(self) -> None:
        for alvo in MatchLifecycle:
            assert not can_transition(MatchLifecycle.CANCELLED, alvo)

    def test_historica_ativa_e_terminal(self) -> None:
        """Uma partida já indexada que precise mudar exige reconstrução do
        índice — operação administrativa deliberada, não uma transição que um
        worker dispara sozinho."""
        assert allowed_transitions(MatchLifecycle.HISTORICAL_ACTIVE) == frozenset()
        assert MatchLifecycle.HISTORICAL_ACTIVE.is_terminal

    def test_o_erro_lista_o_que_era_possivel(self) -> None:
        """ "Transição inválida" manda quem lê procurar o grafo; listar os
        alvos permitidos resolve na mesma linha."""
        with pytest.raises(IllegalTransitionError) as erro:
            transition_to(MatchLifecycle.DISCOVERED, MatchLifecycle.LIVE, at=AGORA, reason="x")
        assert "allowed" in erro.value.context
        assert "SCHEDULED" in erro.value.context["allowed"]


class TestEstadosExcepcionais:
    def test_adiada_volta_para_agendada(self) -> None:
        """Adiada é remarcada, e é a mesma partida."""
        assert can_transition(MatchLifecycle.POSTPONED, MatchLifecycle.SCHEDULED)

    def test_abandonada_ainda_vai_para_reconciliacao(self) -> None:
        """O que aconteceu até a interrupção é fato, e às vezes o resultado é
        homologado depois."""
        assert can_transition(
            MatchLifecycle.ABANDONED, MatchLifecycle.FINISHED_PENDING_RECONCILIATION
        )

    def test_revisao_humana_alcanca_os_tres_fechamentos(self) -> None:
        """O humano pode decidir três coisas: seguir, invalidar, ou marcar
        como abandonada."""
        saidas = allowed_transitions(MatchLifecycle.REVIEW_REQUIRED)
        assert MatchLifecycle.RECONCILED in saidas
        assert MatchLifecycle.DATA_INVALID in saidas
        assert MatchLifecycle.ABANDONED in saidas


class TestInvarianteDeAtivacaoHistorica:
    """ADR-0007. O invariante que impede self-leakage.

    Uma partida ao vivo presente no índice que ela própria consulta encontra a
    si mesma entre os "jogos históricos parecidos". O sintoma é traiçoeiro
    porque é BOM: as métricas sobem, e o sistema só falha em produção contra
    partidas que nunca viu.
    """

    def test_so_historical_active_alimenta_o_indice(self) -> None:
        for estado in MatchLifecycle:
            esperado = estado is MatchLifecycle.HISTORICAL_ACTIVE
            assert estado.can_feed_historical_index is esperado, estado

    def test_partida_ao_vivo_e_recusada_pelo_indice(self) -> None:
        with pytest.raises(InvariantViolationError) as erro:
            assert_can_feed_historical_index(MatchLifecycle.LIVE)
        assert erro.value.context["state"] == "LIVE"
        assert "a si mesma" in erro.value.context["why"]

    def test_reconciliada_ainda_nao_basta(self) -> None:
        """Fatos fechados não são o mesmo que features construídas. Entre
        RECONCILED e HISTORICAL_ACTIVE existe a construção, e um vetor
        inexistente no índice é um vizinho que ninguém acha."""
        with pytest.raises(InvariantViolationError):
            assert_can_feed_historical_index(MatchLifecycle.RECONCILED)
        with pytest.raises(InvariantViolationError):
            assert_can_feed_historical_index(MatchLifecycle.HISTORICAL_PENDING_BUILD)

    def test_historica_ativa_passa(self) -> None:
        assert_can_feed_historical_index(MatchLifecycle.HISTORICAL_ACTIVE)


class TestGrafoCompleto:
    def test_todo_estado_tem_saidas_declaradas(self) -> None:
        """Um estado ausente do grafo estouraria KeyError na primeira
        transição a partir dele — em produção, não aqui."""
        for estado in MatchLifecycle:
            allowed_transitions(estado)

    def test_nenhum_estado_transiciona_para_si_mesmo(self) -> None:
        """Auto-transição esconde um no-op como se fosse mudança, e polui a
        trilha de auditoria com linhas que não dizem nada."""
        for estado in MatchLifecycle:
            assert estado not in allowed_transitions(estado), estado
