"""O guarda temporal e a projeção efetiva — caso a caso.

CADA TESTE AQUI É UM VAZAMENTO CONCRETO que o PR-05.1 existe para tornar
impossível. Eles são pequenos de propósito: um vazamento que só aparece num
cenário grande é um vazamento que ninguém consegue reproduzir.

    §69   evento do futuro                 negado
    §70   evento do passado                permitido
    §71   empate de relógio com sequência  o desempate decide
    §72   substituição futura              nunca afeta o estado
    §73   resultado final                  negado intra-jogo
    §74   agregado final                   negado sem carimbo
    §75   cotação posterior                negada
    §76   correção não conhecida           estado anterior permanece
    §77   correção conhecida               estado atualiza
    §78   correção sem carimbo             fail-closed
    §79   verdade retrospectiva            só para auditoria
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.features.availability import (
    FactKind,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.leakage import (
    FactTiming,
    LeakageReason,
    LeakageVerdict,
    TemporalLeakageGuard,
)
from sports_intelligence.domain.features.projection import (
    EffectiveEventProjection,
)
from sports_intelligence.domain.features.temporal import (
    FeatureAsOf,
    MatchTimePoint,
    TemporalMode,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period
from tests.support.feature_fixtures import (
    CORRECAO_C2,
    GOL_C,
    PARTIDA,
    _id,
    conhecimento_das_correcoes,
    contexto,
    corte,
    cotacao,
    cotacao_sem_carimbo,
    evento,
    historia,
    partida,
    relogio_de_parede,
)


def _guarda(policy: TemporalAvailabilityPolicy | None = None) -> TemporalLeakageGuard:
    return TemporalLeakageGuard(policy=policy or TemporalAvailabilityPolicy.default())


def _ponto(
    minuto: int, *, periodo: Period = Period.SECOND_HALF, seq: int | None = None
) -> MatchTimePoint:
    return MatchTimePoint.of(periodo, minuto, sequence=seq)


class TestOEventoNoTempo:
    """§69, §70, §71."""

    def test_evento_do_futuro_e_negado(self) -> None:
        decisao = _guarda().evaluate(FactTiming.event(_ponto(64)), corte(63))
        assert decisao.verdict is LeakageVerdict.DENIED
        assert decisao.reason is LeakageReason.EFFECTIVE_TIME_AFTER_CUTOFF

    def test_evento_do_passado_e_permitido(self) -> None:
        decisao = _guarda().evaluate(FactTiming.event(_ponto(62)), corte(63))
        assert decisao.verdict is LeakageVerdict.ALLOWED

    def test_o_evento_no_proprio_minuto_do_corte_entra(self) -> None:
        """`<=` e não `<`: um estado «aos 63» inclui o que aconteceu aos 63."""
        assert _guarda().evaluate(FactTiming.event(_ponto(63)), corte(63)).admits

    def test_a_fase_pesa_mais_que_o_minuto(self) -> None:
        """§8. O minuto 40 do segundo tempo é DEPOIS do minuto 44 do primeiro —
        e um contrato temporal que fosse só `minute: int` erraria isto."""
        do_primeiro = FactTiming.event(_ponto(44, periodo=Period.FIRST_HALF))
        corte_do_segundo = corte(40, periodo=Period.SECOND_HALF)
        assert _guarda().evaluate(do_primeiro, corte_do_segundo).admits

    def test_acrescimo_nao_e_achatado_no_minuto(self) -> None:
        """§9. `45+3` não vira `48`: um corte no minuto 45 do primeiro tempo
        SEM acréscimo não inclui o que aconteceu em `45+3`."""
        no_acrescimo = FactTiming.event(MatchTimePoint.of(Period.FIRST_HALF, 45, 3))
        no_minuto = corte(45, periodo=Period.FIRST_HALF)
        assert not _guarda().evaluate(no_acrescimo, no_minuto).admits

    def test_o_desempate_por_sequencia_decide_o_empate_de_relogio(self) -> None:
        """§71. Dois eventos no mesmo relógio: só os de sequência anterior ao
        corte entram, quando o corte declara sequência."""
        corte_sensivel = FeatureAsOf.at(PARTIDA, Period.SECOND_HALF, 63, sequence=5)
        antes = FactTiming.event(_ponto(63, seq=4))
        depois = FactTiming.event(_ponto(63, seq=6))
        assert _guarda().evaluate(antes, corte_sensivel).admits
        assert not _guarda().evaluate(depois, corte_sensivel).admits

    def test_sem_desempate_o_corte_inclui_o_relogio_inteiro(self) -> None:
        """A decisão é explícita: sem sequência declarada, tudo daquele
        relógio entra."""
        assert _guarda().evaluate(FactTiming.event(_ponto(63, seq=99)), corte(63)).admits


class TestOResultadoEOAgregado:
    """§13, §14, §15, §73, §74."""

    def test_o_resultado_final_e_negado_intra_jogo(self) -> None:
        decisao = _guarda().evaluate(FactTiming(kind=FactKind.MATCH_RESULT), corte(63))
        assert decisao.verdict is LeakageVerdict.DENIED
        assert decisao.reason is LeakageReason.POST_MATCH_ONLY

    def test_o_resultado_final_e_permitido_apos_o_apito(self) -> None:
        pos_jogo = FeatureAsOf.at(PARTIDA, Period.FULL_TIME)
        assert _guarda().evaluate(FactTiming(kind=FactKind.MATCH_RESULT), pos_jogo).admits

    def test_o_agregado_final_e_negado_intra_jogo(self) -> None:
        """§15. `HOME_SHOTS = 14` não é `shots_home_at_63 = 14`."""
        decisao = _guarda().evaluate(
            FactTiming(kind=FactKind.FINAL_AGGREGATE, label="HOME_SHOTS=14"), corte(63)
        )
        assert decisao.reason is LeakageReason.POST_MATCH_ONLY

    def test_nem_o_modo_retrospectivo_libera_o_agregado_intra_jogo(self) -> None:
        """§28. `CANONICAL_FINAL` dispensa prova de conhecimento, e não
        transforma um número do fim do jogo em estado do minuto 63."""
        retrospectivo = corte(63, mode=TemporalMode.CANONICAL_FINAL)
        assert (
            not _guarda().evaluate(FactTiming(kind=FactKind.FINAL_AGGREGATE), retrospectivo).admits
        )

    def test_o_contexto_nao_entrega_o_resultado_intra_jogo(self) -> None:
        """§14. E a distinção entre «não existe» e «existe e é do futuro»
        sobrevive: `has_result_in_corpus` continua verdadeiro."""
        intra = contexto(as_of=corte(63))
        assert intra.result is None
        assert intra.has_result_in_corpus

    def test_o_contexto_entrega_o_resultado_apos_o_apito(self) -> None:
        pos = contexto(as_of=FeatureAsOf.at(PARTIDA, Period.FULL_TIME))
        assert pos.result is not None
        assert pos.result.regular_time is not None


class TestAsOdds:
    """§17, §18, §75."""

    def test_cotacao_anterior_ao_corte_e_permitida(self) -> None:
        timing = FactTiming(kind=FactKind.ODDS_OBSERVATION, knowledge=relogio_de_parede(62.9))
        assert _guarda().evaluate(timing, corte(63, conhecimento=63)).admits

    def test_cotacao_posterior_ao_corte_e_negada(self) -> None:
        timing = FactTiming(kind=FactKind.ODDS_OBSERVATION, knowledge=relogio_de_parede(63.1))
        decisao = _guarda().evaluate(timing, corte(63, conhecimento=63))
        assert decisao.reason is LeakageReason.KNOWLEDGE_TIME_AFTER_CUTOFF

    def test_cotacao_sem_carimbo_e_desconhecida_e_nao_permitida(self) -> None:
        """§18. Não inferir disponibilidade pela existência da linha."""
        decisao = _guarda().evaluate(
            FactTiming(kind=FactKind.ODDS_OBSERVATION), corte(63, conhecimento=63)
        )
        assert decisao.verdict is LeakageVerdict.UNKNOWN
        assert decisao.reason is LeakageReason.MISSING_OBSERVATION_TIMESTAMP

    def test_cotacao_com_carimbo_e_corte_sem_conhecimento_fica_desconhecida(self) -> None:
        """Fail-closed dos dois lados: sem os dois carimbos não há comparação."""
        timing = FactTiming(kind=FactKind.ODDS_OBSERVATION, knowledge=relogio_de_parede(10))
        decisao = _guarda().evaluate(timing, corte(63))
        assert decisao.verdict is LeakageVerdict.UNKNOWN
        assert decisao.reason is LeakageReason.MISSING_KNOWLEDGE_CUTOFF

    def test_a_cotacao_de_fechamento_nao_vira_pre_jogo(self) -> None:
        """§18. A classe dela é desconhecida, e o guarda recusa."""
        decisao = _guarda().evaluate(
            FactTiming(kind=FactKind.ODDS_CLOSING), corte(63, conhecimento=63)
        )
        assert decisao.verdict is LeakageVerdict.UNKNOWN
        assert decisao.reason is LeakageReason.UNKNOWN_AVAILABILITY

    def test_as_cotacoes_do_cenario_se_distinguem(self) -> None:
        antes, depois = cotacao(62), cotacao(64)
        assert antes.observed_at is not None
        assert depois.observed_at is not None
        assert antes.observed_at < depois.observed_at
        assert cotacao_sem_carimbo().observed_at is None


class TestAEscalacaoEASubstituicao:
    """§19, §20, §72."""

    def test_a_escalacao_inicial_e_pre_jogo(self) -> None:
        assert _guarda().evaluate(FactTiming(kind=FactKind.LINEUP_INITIAL), corte(1)).admits

    def test_a_substituicao_futura_nunca_entra(self) -> None:
        """§72. Uma troca aos 70 não pode afetar quem está em campo aos 63."""
        projecao = contexto(as_of=corte(63)).events
        tipos = [p.event.type.value for p in projecao.events]
        assert tipos.count("SUBSTITUTION") == 1  # só a dos 40 minutos

    def test_a_substituicao_passada_entra(self) -> None:
        aos_45 = contexto(as_of=corte(45, periodo=Period.FIRST_HALF)).events
        assert any(p.event.type.value == "SUBSTITUTION" for p in aos_45.events)


class TestARevisao:
    """§22, §25, §26, §76, §77, §78."""

    def test_correcao_sem_carimbo_nao_e_aplicada(self) -> None:
        """§78. A política padrão trata correção sem evidência como
        retrospectiva — e o modo causal não a aplica."""
        projecao = contexto(as_of=corte(63)).events
        ids = set(projecao.ids())
        assert _id(GOL_C) in ids
        assert _id(CORRECAO_C2) not in ids
        assert projecao.excluded_by_reason["RETROSPECTIVE_ONLY"] == 1

    def test_o_original_fica_marcado_como_correcao_retida(self) -> None:
        """Quem lê a projeção precisa distinguir «não foi corrigido» de «a
        correção ainda não era sabida»."""
        projecao = contexto(as_of=corte(63)).events
        do_gol = next(p for p in projecao.events if p.id == _id(GOL_C))
        assert do_gol.correction_withheld

    def test_correcao_conhecida_antes_do_corte_e_aplicada(self) -> None:
        """§77. Com carimbo e corte de conhecimento posterior, o estado
        atualiza — e o original sai da visão."""
        projecao = contexto(
            as_of=corte(63, conhecimento=40),
            knowledge=conhecimento_das_correcoes(),
        ).events
        ids = set(projecao.ids())
        assert _id(CORRECAO_C2) in ids
        assert _id(GOL_C) not in ids

    def test_correcao_conhecida_depois_do_corte_nao_e_aplicada(self) -> None:
        """§76. O carimbo diz 35' e o corte de conhecimento é 33': o replay
        mantém o estado anterior."""
        projecao = contexto(
            as_of=corte(34, periodo=Period.FIRST_HALF, conhecimento=33),
            knowledge=conhecimento_das_correcoes(),
        ).events
        ids = set(projecao.ids())
        assert _id(GOL_C) in ids
        assert _id(CORRECAO_C2) not in ids
        assert projecao.excluded_by_reason["KNOWLEDGE_TIME_AFTER_CUTOFF"] == 1

    def test_a_verdade_retrospectiva_enxerga_a_correcao(self) -> None:
        """§79. `CANONICAL_FINAL` serve à auditoria — e o §80 impede que um
        espaço comparável ao vivo a use."""
        projecao = contexto(as_of=corte(63, mode=TemporalMode.CANONICAL_FINAL)).events
        ids = set(projecao.ids())
        assert _id(CORRECAO_C2) in ids
        assert _id(GOL_C) not in ids

    def test_a_retrospectiva_continua_sem_enxergar_o_futuro(self) -> None:
        """Ela dispensa prova de conhecimento, e não a causalidade de
        ocorrência: o gol dos 78 continua fora de um estado de 63."""
        from tests.support.feature_fixtures import GOL_F

        projecao = contexto(as_of=corte(63, mode=TemporalMode.CANONICAL_FINAL)).events
        assert _id(GOL_F) not in set(projecao.ids())


class TestAProjecao:
    """§23, §24, §98, §131."""

    def test_a_projecao_nao_muta_a_historia(self) -> None:
        """§24. O corpus continua append-only; a projeção é derivada."""
        completa = historia()
        antes = [(e.id, e.status) for e in completa]
        contexto(as_of=corte(63), eventos=completa)
        assert [(e.id, e.status) for e in completa] == antes

    def test_a_ordem_de_entrada_nao_muda_a_projecao(self) -> None:
        """§131. Mudar a ordem física das linhas sem mudar a cronologia
        produz a MESMA visão efetiva."""
        completa = historia()
        direta = contexto(as_of=corte(63), eventos=completa).events
        invertida = contexto(as_of=corte(63), eventos=tuple(reversed(completa))).events
        assert direta.ids() == invertida.ids()

    def test_a_projecao_conta_o_que_ficou_de_fora_por_motivo(self) -> None:
        """«12 vistos» não explica nada quando alguém esperava 15."""
        projecao = contexto(as_of=corte(63)).events
        assert projecao.excluded_by_reason == {
            "EFFECTIVE_TIME_AFTER_CUTOFF": 2,
            "RETROSPECTIVE_ONLY": 1,
        }

    def test_evento_de_outra_partida_e_recusado_e_nao_filtrado(self) -> None:
        """Filtrar em silêncio produziria uma projeção plausível de um jogo que
        não é o pedido — o pior desfecho, porque nada denuncia."""
        from dataclasses import replace

        from sports_intelligence.domain.shared.identity import MatchId

        estranho = replace(evento("estranho", minuto=5), match_id=MatchId.derive("pr051", "outra"))
        with pytest.raises(ValidationError, match="outra partida"):
            EffectiveEventProjection.with_policy(TemporalAvailabilityPolicy.default()).project(
                (estranho,), as_of=corte(63)
            )

    def test_o_cancelado_nao_entra_na_visao_efetiva(self) -> None:
        """Um gol anulado não faz parte do estado — e continua no corpus."""
        from sports_intelligence.domain.events.canonical import EventStatus

        anulado = evento("anulado", minuto=25, status=EventStatus.CANCELLED)
        projecao = EffectiveEventProjection.with_policy(
            TemporalAvailabilityPolicy.default()
        ).project((anulado,), as_of=corte(63))
        assert projecao.size == 0

    def test_a_projecao_e_pura_e_repetivel(self) -> None:
        projecao = EffectiveEventProjection.with_policy(TemporalAvailabilityPolicy.default())
        primeira = projecao.project(historia(), as_of=corte(63))
        segunda = projecao.project(historia(), as_of=corte(63))
        assert primeira.ids() == segunda.ids()


class TestAPoliticaEstrita:
    """§12, §27. A suposição padrão é uma escolha, e há outra."""

    def test_a_politica_estrita_recusa_evento_sem_carimbo(self) -> None:
        """Sob ela, um corpus sem carimbo de observação não produz feature
        intra-jogo. É honesto e pouco útil — e é por isso que não é o padrão."""
        projecao = contexto(
            as_of=corte(63, conhecimento=63),
            policy=TemporalAvailabilityPolicy.strict_observed(),
        ).events
        assert projecao.size == 0
        assert projecao.excluded_by_reason["MISSING_OBSERVATION_TIMESTAMP"] >= 4

    def test_a_politica_padrao_admite_o_evento_observavel(self) -> None:
        assert contexto(as_of=corte(63)).events.size == 4


class TestOContexto:
    """§93, §94, §97."""

    def test_o_contexto_e_de_uma_partida_so(self) -> None:
        from dataclasses import replace

        from sports_intelligence.domain.features.context import CanonicalFeatureContext
        from sports_intelligence.domain.shared.identity import MatchId

        with pytest.raises(ValidationError, match="carregando a partida"):
            CanonicalFeatureContext(
                as_of=corte(63),
                source=contexto().source,
                policy=TemporalAvailabilityPolicy.default(),
                match=replace(partida(), id=MatchId.derive("pr051", "outra-partida")),
            )

    def test_o_contexto_declara_a_origem_do_corpus(self) -> None:
        """§60. Sem isso, um valor calculado hoje não teria como ser
        reproduzido contra o mesmo dado amanhã."""
        atual = contexto()
        assert atual.source.corpus_fingerprint.value
        assert "corpus_fingerprint" in atual.source.as_canonical()

    def test_a_procedencia_temporal_do_contexto_e_deterministica(self) -> None:
        assert contexto().digest() == contexto().digest()
