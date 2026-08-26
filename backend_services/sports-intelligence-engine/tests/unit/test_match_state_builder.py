"""O construtor de estado — do corpus publicado ao `HistoricalMatchState`.

O QUE ESTES TESTES PROVAM, e que nem o reducer nem os componentes provam
sozinhos:

    o CORTE manda                 nada depois dele entra, em nenhum componente
    a COBERTURA manda             sem `EVENT` publicado, não há placar afirmável
    a DISPONIBILIDADE é local     escalação ausente não apaga o placar
    o RESULTADO não alimenta      2-1 no banco não faz o estado de 63' virar 2-1
    a IMPRESSÃO é da causalidade  corpus e política entram na identidade

O CASO MAIS IMPORTANTE É O DO §100. O resultado final está na entrada — a
leitura o traz sempre —, e ele só pode ser LIDO num corte pós-jogo, e mesmo lá
só para conferir. Um estado intra-jogo que soubesse do 2-1 seria o vazamento
mais caro do motor inteiro, porque o número pareceria certo.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.availability import (
    FeatureAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.projection import EventKnowledge
from sports_intelligence.domain.features.state.builder import (
    HistoricalMatchStateBuilder,
)
from sports_intelligence.domain.features.state.issues import (
    StateIssueCode,
    StateIssueSeverity,
)
from sports_intelligence.domain.features.state.match_state import (
    STATE_FINGERPRINT_ALGORITHM,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import CASA, FORA, PARTIDA, corte, cotacao, origem
from tests.support.state_fixtures import (
    CASA_BANCO,
    CASA_TITULARES,
    FORA_TITULARES,
    GOL_CASA_70,
    TODAS_AS_FAMILIAS,
    construir,
    entrada,
    escalacoes,
    evento,
    historia,
    id_de,
    origem_completa,
    passado,
    resultado_final,
)


def codigos(resultado: object) -> set[StateIssueCode]:
    return {i.code for i in resultado.issues}  # type: ignore[attr-defined]


# ------------------------------------------------------- caminho feliz --


class TestReconstrucaoDeReferencia:
    """O corte de 63' do cenário: 1-1, onze contra dez, um cartão."""

    def test_o_placar_e_o_dos_eventos_ate_o_corte(self) -> None:
        estado = construir().state
        assert (estado.score.home, estado.score.away) == (1, 1)
        assert estado.score.is_available

    def test_o_campo_reflete_substituicao_e_expulsao(self) -> None:
        estado = construir().state
        casa = estado.on_field.team(CASA)
        fora = estado.on_field.team(FORA)
        assert casa is not None
        assert fora is not None
        assert casa.size == 11
        assert fora.size == 10
        assert casa.has(CASA_BANCO[0])
        assert not casa.has(CASA_TITULARES[10])

    def test_a_disciplina_conta_os_cartoes_do_passado(self) -> None:
        estado = construir().state
        casa = estado.discipline.team(CASA)
        fora = estado.discipline.team(FORA)
        assert casa is not None
        assert fora is not None
        assert (casa.yellow_cards, casa.dismissals) == (1, 0)
        assert (fora.yellow_cards, fora.dismissals) == (0, 1)

    def test_o_estado_de_referencia_nao_tem_problema_degradante(self) -> None:
        resultado = construir(entrada(odds=(cotacao(-60.0),)), as_of=corte(conhecimento=63))
        degradantes = [i for i in resultado.issues if i.severity is StateIssueSeverity.DEGRADED]
        assert degradantes == []

    def test_o_estado_carrega_o_contexto_publicado(self) -> None:
        estado = construir().state
        assert estado.context.competition_code == "PREMIER_LEAGUE"
        assert estado.context.season_label == "2025/26"
        assert estado.identity.home_team_id == CASA
        assert estado.identity.away_team_id == FORA


# ---------------------------------------------------------- causalidade --


class TestCausalidade:
    def test_nenhum_evento_do_futuro_entra_no_estado(self) -> None:
        """§126 — o gol dos 70 não existe num estado de 63'."""
        estado = construir().state
        assert estado.events.effective_count == len(passado())
        assert estado.provenance.effective_events.count == len(passado())
        assert id_de(GOL_CASA_70) not in {c.reference for c in estado.provenance.score.sample}

    def test_o_corte_pre_jogo_nao_ve_nenhum_evento(self) -> None:
        """§81 — antes do apito, o placar é 0-0 OBSERVADO, e não desconhecido."""
        estado = construir(as_of=FeatureAsOf.pre_match(PARTIDA)).state
        assert estado.events.effective_count == 0
        assert (estado.score.home, estado.score.away) == (0, 0)
        assert estado.score.is_available
        casa = estado.on_field.team(CASA)
        assert casa is not None
        assert casa.size == 11

    def test_o_corte_pos_jogo_ve_a_partida_inteira(self) -> None:
        estado = construir(as_of=FeatureAsOf.at(PARTIDA, Period.FULL_TIME, 90)).state
        assert (estado.score.home, estado.score.away) == (2, 1)
        assert estado.events.effective_count == len(historia())

    def test_o_corte_de_outra_partida_e_recusado(self) -> None:
        outra = MatchId.derive("pr052", "outra-partida")
        with pytest.raises(ValidationError, match="o corte é de"):
            HistoricalMatchStateBuilder(policy=TemporalAvailabilityPolicy.default()).build(
                entrada(),
                as_of=FeatureAsOf.at(outra, Period.SECOND_HALF, 63),
                source=origem_completa(),
            )

    def test_evento_de_outra_partida_na_entrada_e_erro(self) -> None:
        """§113 — filtrar em silêncio produziria um jogo que não aconteceu."""
        outra = MatchId.derive("pr052", "outra-partida")
        intruso = evento("intruso", tipo=EventType.GOAL, minuto=10, time=CASA, match_id=outra)
        with pytest.raises(ValidationError, match="é da partida"):
            entrada(eventos=(*passado(), intruso))


# ------------------------------------------------- resultado publicado --


class TestResultadoPublicado:
    def test_o_resultado_final_nao_alimenta_o_placar_intra_jogo(self) -> None:
        """§10, §12 — o 2-1 do banco não pode virar o placar dos 63'."""
        estado = construir(entrada(result=resultado_final())).state
        assert (estado.score.home, estado.score.away) == (1, 1)

    def test_o_resultado_confere_no_apito_final_e_nao_acusa_nada(self) -> None:
        resultado = construir(
            entrada(result=resultado_final()),
            as_of=FeatureAsOf.at(PARTIDA, Period.FULL_TIME, 90),
        )
        assert StateIssueCode.SCORE_RESULT_MISMATCH not in codigos(resultado)

    def test_a_divergencia_e_registrada_e_nao_corrigida(self) -> None:
        """§101 — o estado continua sendo o que os eventos dizem."""
        resultado = construir(
            entrada(result=MatchResult(regular_time=Score(home=5, away=0))),
            as_of=FeatureAsOf.at(PARTIDA, Period.FULL_TIME, 90),
        )
        assert StateIssueCode.SCORE_RESULT_MISMATCH in codigos(resultado)
        assert (resultado.state.score.home, resultado.state.score.away) == (2, 1)
        divergencia = next(
            i for i in resultado.issues if i.code is StateIssueCode.SCORE_RESULT_MISMATCH
        )
        # A SEVERIDADE É `NOTED` E NÃO `DEGRADED` (§104): o placar dos 63' não
        # fica menos confiável por o resultado publicado discordar do apito
        # final. O que existe é uma discordância entre duas fontes, e ela
        # precisa aparecer sem apagar o que os eventos dizem.
        assert divergencia.severity is StateIssueSeverity.NOTED
        assert resultado.state.score.is_available


# ------------------------------------------------------------ cobertura --


class TestCobertura:
    def test_sem_a_familia_event_o_placar_nao_e_afirmavel(self) -> None:
        """§14, §40 — «zero a zero» é uma afirmação que ninguém pode fazer."""
        resultado = construir(
            entrada(
                families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP}),
            )
        )
        estado = resultado.state
        assert not estado.score.is_available
        assert estado.score.availability is FeatureAvailability.NOT_DECLARED
        assert StateIssueCode.INCOMPLETE_EVENT_HISTORY in codigos(resultado)

    def test_sem_event_a_disciplina_tambem_nao_e_afirmavel(self) -> None:
        """§40 — zero cartões só é fato quando há evento publicado."""
        estado = construir(
            entrada(families=frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP}))
        ).state
        assert estado.availability["discipline"] is FeatureAvailability.NOT_DECLARED
        assert estado.availability["substitutions"] is FeatureAvailability.NOT_DECLARED
        assert estado.availability["events"] is FeatureAvailability.NOT_DECLARED

    def test_sem_escalacao_o_campo_cai_e_o_placar_sobrevive(self) -> None:
        """§106 — a degradação é do componente, e não do estado inteiro."""
        resultado = construir(
            entrada(
                families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}),
                lineups=(),
            )
        )
        estado = resultado.state
        assert not estado.on_field.is_available
        assert estado.score.is_available
        assert (estado.score.home, estado.score.away) == (1, 1)
        assert StateIssueCode.LINEUP_UNAVAILABLE in codigos(resultado)

    def test_escalacao_parcial_nao_se_completa(self) -> None:
        """§23 — dez titulares declarados não viram onze por conveniência."""
        parcial = escalacoes(titulares_casa=CASA_TITULARES[:10])
        resultado = construir(entrada(lineups=parcial))
        casa = resultado.state.on_field.team(CASA)
        fora = resultado.state.on_field.team(FORA)
        assert casa is not None
        assert not casa.is_available
        assert fora is not None
        assert fora.is_available
        assert StateIssueCode.LINEUP_INCOMPLETE in codigos(resultado)

    def test_jogador_nos_dois_times_degrada_o_campo_e_preserva_o_placar(self) -> None:
        """§26, §106 — o defeito é do elenco, e o placar não depende dele."""
        cruzada = escalacoes(titulares_fora=(CASA_TITULARES[0], *FORA_TITULARES[1:]))
        resultado = construir(entrada(lineups=cruzada, eventos=passado()))
        assert StateIssueCode.PLAYER_IN_BOTH_TEAMS in codigos(resultado)
        assert not resultado.state.on_field.is_available
        assert resultado.state.score.is_available

    # O JOGADOR REPETIDO NA MESMA ESCALAÇÃO NÃO CHEGA ATÉ AQUI: o tipo
    # `Lineup` (PR-01) já o recusa na leitura do corpus. A guarda equivalente
    # em `TeamOnFieldState` é segunda linha de defesa e está provada em
    # `test_state_components.py` — testá-la pelo construtor exigiria construir
    # um `Lineup` que o corpus não produz, e um teste sobre um fato impossível
    # não prova nada sobre produção.


# ---------------------------------------------------------------- odds --


class TestOdds:
    def test_sem_a_familia_odds_o_componente_e_nao_declarado(self) -> None:
        estado = construir(
            entrada(families=frozenset({CoverageFamily.MATCH, CoverageFamily.EVENT}))
        ).state
        assert estado.odds.availability is FeatureAvailability.NOT_DECLARED

    def test_com_a_familia_e_sem_cotacao_a_fonte_e_que_falta(self) -> None:
        """§40 aplicado a odds: «publicamos e esta partida não tem» é outro fato."""
        estado = construir(entrada(odds=())).state
        assert estado.odds.availability is FeatureAvailability.SOURCE_UNAVAILABLE

    def test_sem_corte_de_conhecimento_a_cotacao_nao_se_prova(self) -> None:
        """§51 — fail-closed: assumir que já existia é o vazamento do §27."""
        resultado = construir(entrada(odds=(cotacao(-60.0),)))
        assert resultado.state.odds.availability is FeatureAvailability.TEMPORALLY_UNAVAILABLE
        assert StateIssueCode.ODDS_TEMPORAL_UNKNOWN in codigos(resultado)

    def test_com_corte_de_conhecimento_a_cotacao_do_passado_entra(self) -> None:
        estado = construir(
            entrada(odds=(cotacao(-60.0),)),
            as_of=corte(conhecimento=63),
        ).state
        assert estado.odds.count == 1
        assert estado.odds.is_available

    def test_a_cotacao_do_futuro_nao_entra(self) -> None:
        """§46 — a cotação vista aos 80 não existe num estado de 63'."""
        estado = construir(
            entrada(odds=(cotacao(-60.0), cotacao(80.0, valor="9.99"))),
            as_of=corte(conhecimento=63),
        ).state
        assert estado.odds.count == 1
        assert estado.odds.quotes[0].decimal_odds.startswith("1.8")

    def test_o_estado_guarda_a_ultima_de_cada_fluxo(self) -> None:
        """§122 — e não uma pilha de todas as cotações já vistas."""
        estado = construir(
            entrada(
                odds=(
                    cotacao(-60.0, valor="1.70"),
                    cotacao(-30.0, valor="1.80"),
                    cotacao(10.0, valor="1.95"),
                )
            ),
            as_of=corte(conhecimento=63),
        ).state
        assert estado.odds.count == 1
        assert estado.odds.quotes[0].decimal_odds.startswith("1.95")


# --------------------------------------------------------- correções --


class TestCorrecoes:
    def test_a_correcao_ainda_desconhecida_nao_e_aplicada(self) -> None:
        """§17, §45 — o replay não pode aplicar o que ainda não se sabia.

        O gol dos 12 é corrigido por um evento cujo conhecimento só chega aos
        50 minutos de jogo. Num corte de 30 com conhecimento de 30, o estado
        precisa ser o ANTIGO — porque era o que se sabia.
        """
        original = evento(
            "gol-corrigido",
            tipo=EventType.GOAL,
            minuto=12,
            sequencia=1,
            time=CASA,
            jogador_id=CASA_TITULARES[8],
        )
        from sports_intelligence.domain.events.canonical import EventStatus

        corrigido = replace(original, status=EventStatus.CORRECTED)
        sucessor = evento(
            "gol-anulado",
            tipo=EventType.GOAL,
            minuto=12,
            sequencia=1,
            time=FORA,
            jogador_id=FORA_TITULARES[8],
            revision=2,
            supersedes=original.id,
        )
        from tests.support.feature_fixtures import relogio_de_parede

        insumos = entrada(
            eventos=(corrigido, sucessor),
            knowledge=EventKnowledge(by_event={sucessor.id: relogio_de_parede(50)}),
        )
        antes = construir(
            insumos, as_of=corte(30, periodo=Period.FIRST_HALF, conhecimento=30)
        ).state
        depois = construir(
            insumos, as_of=corte(30, periodo=Period.FIRST_HALF, conhecimento=60)
        ).state
        assert (antes.score.home, antes.score.away) == (1, 0)
        assert (depois.score.home, depois.score.away) == (0, 1)

    def test_o_modo_final_dispensa_a_prova_de_conhecimento(self) -> None:
        """§28 — `CANONICAL_FINAL` responde outra pergunta, e é legítima."""
        estado = construir(
            entrada(odds=(cotacao(-60.0),)),
            as_of=corte(mode=TemporalMode.CANONICAL_FINAL),
        ).state
        assert estado.odds.count == 1


# ------------------------------------------------------------ impressão --


class TestImpressao:
    def test_a_mesma_entrada_produz_a_mesma_impressao(self) -> None:
        assert construir().state.fingerprint == construir().state.fingerprint

    def test_cortes_diferentes_produzem_impressoes_diferentes(self) -> None:
        a = construir(as_of=corte(30, periodo=Period.FIRST_HALF)).state
        b = construir(as_of=corte(63)).state
        assert a.fingerprint != b.fingerprint

    def test_corpus_diferente_muda_a_impressao(self) -> None:
        """§8, §70 — dois estados só são comparáveis sob o mesmo corpus."""
        outro = origem(families=TODAS_AS_FAMILIAS, fingerprint="b" * 64)
        estado = (
            HistoricalMatchStateBuilder(policy=TemporalAvailabilityPolicy.default())
            .build(entrada(), as_of=corte(), source=outro)
            .state
        )
        assert estado.fingerprint != construir().state.fingerprint

    def test_politica_diferente_muda_a_impressao(self) -> None:
        """§71 — a causalidade sob a qual o estado foi feito é parte dele."""
        estrita = construir(policy=TemporalAvailabilityPolicy.strict_observed()).state
        assert estrita.fingerprint != construir().state.fingerprint

    def test_a_impressao_declara_o_algoritmo(self) -> None:
        assert construir().state.as_canonical()["algorithm"] == STATE_FINGERPRINT_ALGORITHM

    def test_a_procedencia_entra_na_identidade(self) -> None:
        """§65 — mesmo placar de gols DIFERENTES não é o mesmo estado."""
        canonico = construir().state.as_canonical()
        assert "provenance" in canonico
        assert canonico["provenance"]["score"]["count"] == 2  # type: ignore[index]


# --------------------------------------------------------- parcialidade --


class TestParcialidade:
    def test_o_estado_completo_nao_e_parcial(self) -> None:
        """Todos os componentes afirmáveis — o único caso em que ele é inteiro."""
        estado = construir(entrada(odds=(cotacao(-60.0),)), as_of=corte(conhecimento=63)).state
        assert not estado.is_partial

    def test_familia_nao_publicada_torna_o_estado_parcial(self) -> None:
        """§55 — o corpus sem `ODDS` produz um estado honestamente incompleto.

        Ele não é um estado ERRADO: é um estado que declara o que não pôde
        afirmar. Chamá-lo de completo obrigaria quem consome a descobrir a
        ausência por conta própria, olhando o valor zero.
        """
        estado = construir(
            entrada(families=frozenset(TODAS_AS_FAMILIAS) - {CoverageFamily.ODDS})
        ).state
        assert estado.is_partial
        assert estado.availability["odds"] is FeatureAvailability.NOT_DECLARED
        assert estado.availability["score"].is_available

    def test_um_componente_ausente_torna_o_estado_parcial(self) -> None:
        estado = construir(entrada(lineups=())).state
        assert estado.is_partial
        assert estado.degraded_issues

    def test_a_parcialidade_e_visivel_por_componente(self) -> None:
        estado = construir(entrada(lineups=())).state
        assert estado.availability["score"].is_available
        assert not estado.availability["on_field"].is_available
