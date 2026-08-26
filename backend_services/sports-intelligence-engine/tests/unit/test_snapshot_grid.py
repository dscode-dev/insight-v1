"""A grade de cortes e a divisão do dataset — as duas decisões do PR-05.5.1.

O QUE ESTES TESTES PROVAM, e nenhum outro prova:

    o TAMANHO da grade é 91           1 pré-jogo + 45 + 45, contado à mão
    o ACRÉSCIMO não entra             nem `45+1`, nem `90+1`
    o INTERVALO não entra             `HALF_TIME` não é minuto de jogo
    o PÓS-JOGO não entra              `FULL_TIME` conhece o resultado
    a PRORROGAÇÃO exige PROVA         e a prova tem duas fontes canônicas
    o corte intra-jogo NÃO tem instante de conhecimento
    o corte pré-jogo TEM, e é o apito canônico
    a divisão é ATÔMICA por partida   o mesmo apito dá a mesma metade sempre
    a fronteira é EXCLUSIVA           o jogo exatamente nela cai na avaliação

OS NÚMEROS SÃO CONFERIDOS À MÃO. Um teste que calculasse o esperado com o
código que testa provaria apenas que ele concorda consigo mesmo.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sports_intelligence.domain.events.taxonomy import EventType
from sports_intelligence.domain.features.dataset.grid import (
    EXTRA_TIME_SECOND_LAST_MINUTE,
    GRID_EXCLUSIONS_V1,
    LIVE_COMPARABLE_MINUTE_GRID_V1,
    REGULATION_GRID_SIZE,
    ExtraTimeEvidence,
    ExtraTimeRule,
    GridExclusionReason,
    PreMatchCutoffRule,
    SnapshotGridPolicy,
    canonical_kickoff,
    extra_time_evidence,
    grid_periods,
)
from sports_intelligence.domain.features.dataset.split import (
    DatasetSplit,
    FeatureDatasetSplitPolicy,
    SplitCounts,
)
from sports_intelligence.domain.features.temporal import TemporalMode
from sports_intelligence.domain.matches.result import MatchResult, Score
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant, Period, instant
from tests.support.feature_fixtures import KICKOFF, partida
from tests.support.snapshot_fixtures import evento

PARTIDA = MatchId.derive("pr0551", "grade")


class TestOTamanhoDaGrade:
    def test_a_grade_regulamentar_tem_noventa_e_um_cortes(self) -> None:
        """1 + 45 + 45. O número é a propriedade que torna partidas comparáveis."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert len(pontos) == REGULATION_GRID_SIZE == 91

    def test_o_primeiro_corte_e_o_pre_jogo(self) -> None:
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert pontos[0].index == 0
        assert pontos[0].period is Period.PRE_MATCH
        assert pontos[0].label == "PRE_MATCH"

    def test_os_minutos_vao_de_um_a_noventa_sem_buraco(self) -> None:
        """O minuto 46 é o primeiro do segundo tempo, e o 45 o último do primeiro."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        intra = pontos[1:]
        assert [p.minute for p in intra] == list(range(1, 91))
        primeiro = [p for p in intra if p.period is Period.FIRST_HALF]
        segundo = [p for p in intra if p.period is Period.SECOND_HALF]
        assert [p.minute for p in primeiro] == list(range(1, 46))
        assert [p.minute for p in segundo] == list(range(46, 91))

    def test_o_indice_e_a_coordenada_estavel(self) -> None:
        """Índices contíguos a partir de zero — é por eles que duas partidas
        se alinham numa comparação coluna a coluna."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert [p.index for p in pontos] == list(range(91))

    def test_o_minuto_zero_nao_existe_no_primeiro_tempo(self) -> None:
        """Ele SERIA o pré-jogo, e materializar os dois daria duas linhas para
        o mesmo estado com chaves diferentes."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert not [p for p in pontos if p.period is Period.FIRST_HALF and p.minute == 0]


class TestOQueNaoEntraNaGrade:
    def test_nenhum_corte_tem_acrescimo(self) -> None:
        """`45+1` existe num jogo e não noutro: a grade deixaria de ser a mesma."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert all(p.as_of.position.stoppage == 0 for p in pontos)

    @pytest.mark.parametrize(
        "fase",
        [
            Period.HALF_TIME,
            Period.FULL_TIME,
            Period.PENALTY_SHOOTOUT,
            Period.EXTRA_TIME_BREAK,
        ],
    )
    def test_fases_sem_relogio_ou_com_resposta_ficam_de_fora(self, fase: Period) -> None:
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert not [p for p in pontos if p.period is fase]

    def test_o_catalogo_de_exclusoes_nomeia_cada_ausencia(self) -> None:
        """«Por que o dataset não tem o minuto 45+2?» tem resposta escrita."""
        motivos = {e.reason for e in GRID_EXCLUSIONS_V1}
        assert motivos == set(GridExclusionReason)

    def test_o_catalogo_de_exclusoes_e_serializavel(self) -> None:
        formas = [e.as_canonical() for e in GRID_EXCLUSIONS_V1]
        assert all(set(f) == {"reason", "subject"} for f in formas)


class TestAProrrogacao:
    def test_sem_prova_a_grade_para_nos_noventa(self) -> None:
        pontos = SnapshotGridPolicy().points_for(
            PARTIDA, kickoff=KICKOFF, extra_time=ExtraTimeEvidence.none()
        )
        assert len(pontos) == 91

    def test_com_prova_a_grade_vai_ate_cento_e_vinte(self) -> None:
        pontos = SnapshotGridPolicy().points_for(
            PARTIDA,
            kickoff=KICKOFF,
            extra_time=ExtraTimeEvidence(proven=True, source="teste"),
        )
        assert len(pontos) == 121
        assert pontos[-1].minute == EXTRA_TIME_SECOND_LAST_MINUTE
        assert pontos[-1].period is Period.EXTRA_TIME_SECOND

    def test_um_evento_em_prorrogacao_e_prova_canonica(self) -> None:
        prova = extra_time_evidence(
            events=(
                evento(
                    "gol-da-prorrogacao",
                    tipo=EventType.GOAL,
                    minuto=97,
                    periodo=Period.EXTRA_TIME_FIRST,
                ),
            )
        )
        assert prova.proven
        assert prova.source == "CANONICAL_EVENT_IN_EXTRA_TIME"

    def test_o_placar_de_prorrogacao_tambem_e_prova(self) -> None:
        prova = extra_time_evidence(
            result=MatchResult(
                regular_time=Score(home=1, away=1),
                extra_time=Score(home=2, away=1),
            )
        )
        assert prova.proven
        assert prova.source == "MATCH_RESULT_EXTRA_TIME_SCORE"

    def test_sem_evento_nem_placar_nao_ha_prorrogacao(self) -> None:
        assert not extra_time_evidence().proven
        assert not extra_time_evidence(
            result=MatchResult(regular_time=Score(home=2, away=1))
        ).proven

    def test_a_regra_never_ignora_ate_a_prova(self) -> None:
        """Uma grade estritamente regulamentar é uma declaração legítima."""
        politica = SnapshotGridPolicy(extra_time=ExtraTimeRule.NEVER)
        pontos = politica.points_for(
            PARTIDA, kickoff=KICKOFF, extra_time=ExtraTimeEvidence(proven=True)
        )
        assert len(pontos) == 91

    def test_nao_existe_regra_de_prorrogacao_sempre(self) -> None:
        """`ALWAYS` inventaria trinta linhas para 97% dos jogos."""
        assert {r.value for r in ExtraTimeRule} == {
            "ONLY_WITH_CANONICAL_EVIDENCE",
            "NEVER",
        }


class TestOCorteDeConhecimento:
    def test_o_corte_intra_jogo_nao_tem_instante(self) -> None:
        """`kickoff + minuto` é fabricação: ignora intervalo e acréscimos."""
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        intra = [p for p in pontos if p.period is not Period.PRE_MATCH]
        assert all(p.as_of.knowledge_cutoff is None for p in intra)

    def test_o_corte_pre_jogo_usa_o_apito_canonico(self) -> None:
        pontos = SnapshotGridPolicy().points_for(PARTIDA, kickoff=KICKOFF)
        assert pontos[0].as_of.knowledge_cutoff == KICKOFF

    def test_a_politica_pode_dispensar_o_instante_do_pre_jogo(self) -> None:
        politica = SnapshotGridPolicy(pre_match_cutoff=PreMatchCutoffRule.NONE)
        pontos = politica.points_for(PARTIDA, kickoff=KICKOFF)
        assert pontos[0].as_of.knowledge_cutoff is None

    def test_o_apito_canonico_prefere_o_real_ao_marcado(self) -> None:
        from dataclasses import replace

        real = instant(KICKOFF + timedelta(minutes=17))
        assert canonical_kickoff(partida()) == KICKOFF
        assert canonical_kickoff(replace(partida(), actual_kickoff=real)) == real


class TestAIdentidadeDaGrade:
    def test_a_grade_padrao_tem_o_nome_declarado(self) -> None:
        assert SnapshotGridPolicy().name == LIVE_COMPARABLE_MINUTE_GRID_V1

    def test_a_impressao_e_estavel_entre_instancias(self) -> None:
        assert SnapshotGridPolicy().fingerprint == SnapshotGridPolicy().fingerprint

    def test_mudar_a_regra_de_prorrogacao_muda_a_impressao(self) -> None:
        """Duas construções sob grades diferentes NÃO são comparáveis, e a
        impressão é o que impede a diferença de passar despercebida."""
        assert (
            SnapshotGridPolicy().fingerprint
            != SnapshotGridPolicy(extra_time=ExtraTimeRule.NEVER).fingerprint
        )

    def test_o_modo_canonical_final_e_recusado(self) -> None:
        """Ao vivo o final não é conhecido — a população deixaria de ser
        reproduzível pela produção."""
        with pytest.raises(ValidationError, match="AS_KNOWN"):
            SnapshotGridPolicy(mode=TemporalMode.CANONICAL_FINAL)

    def test_um_segundo_tempo_antes_do_primeiro_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="grade vazia"):
            SnapshotGridPolicy(first_half_last_minute=45, second_half_last_minute=40)

    def test_os_periodos_possiveis_saem_da_politica(self) -> None:
        assert set(grid_periods(SnapshotGridPolicy())) == {
            Period.PRE_MATCH,
            Period.FIRST_HALF,
            Period.SECOND_HALF,
            Period.EXTRA_TIME_FIRST,
            Period.EXTRA_TIME_SECOND,
        }
        assert set(grid_periods(SnapshotGridPolicy(extra_time=ExtraTimeRule.NEVER))) == {
            Period.PRE_MATCH,
            Period.FIRST_HALF,
            Period.SECOND_HALF,
        }


# =============================================================== divisão ==

FRONTEIRA = instant(datetime(2026, 4, 1, 0, 0, tzinfo=UTC))


def _sem_fuso(momento: Instant) -> Instant:
    """O mesmo instante SEM fuso — o defeito que a política existe para pegar.

    O VALOR NUNCA PASSOU POR `instant()`, e é a prova de que a defesa é em
    profundidade: `instant()` já recusa ingênuo, então só um valor construído
    por fora chega até a política. É exatamente o caso que a guarda dela cobre.
    """
    return momento.replace(tzinfo=None)


class TestADivisao:
    def test_antes_da_fronteira_e_referencia(self) -> None:
        politica = FeatureDatasetSplitPolicy(reference_end_exclusive=FRONTEIRA)
        antes = instant(datetime(2026, 3, 31, 23, 59, tzinfo=UTC))
        assert politica.assign(kickoff=antes) is DatasetSplit.REFERENCE

    def test_exatamente_na_fronteira_e_avaliacao(self) -> None:
        """A fronteira é EXCLUSIVA, e a convenção precisa ser UMA."""
        politica = FeatureDatasetSplitPolicy(reference_end_exclusive=FRONTEIRA)
        assert politica.assign(kickoff=FRONTEIRA) is DatasetSplit.EVALUATION

    def test_a_decisao_e_por_apito_e_portanto_por_partida(self) -> None:
        """A assinatura recebe um apito e devolve uma metade: não há como dar
        respostas diferentes para dois minutos do mesmo jogo."""
        politica = FeatureDatasetSplitPolicy(reference_end_exclusive=FRONTEIRA)
        apito = instant(datetime(2026, 3, 14, 19, 45, tzinfo=UTC))
        assert {politica.assign(kickoff=apito) for _ in range(91)} == {DatasetSplit.REFERENCE}

    def test_a_fronteira_sem_fuso_e_recusada(self) -> None:
        """«01/06 às 00:00» é um instante diferente em cada fuso."""
        with pytest.raises(ValidationError, match="sem fuso"):
            FeatureDatasetSplitPolicy(reference_end_exclusive=_sem_fuso(FRONTEIRA))

    def test_o_apito_sem_fuso_e_recusado(self) -> None:
        politica = FeatureDatasetSplitPolicy(reference_end_exclusive=FRONTEIRA)
        with pytest.raises(ValidationError, match="sem fuso"):
            politica.assign(kickoff=_sem_fuso(KICKOFF))

    def test_so_existem_duas_metades(self) -> None:
        """`VALIDATION` exigiria uma segunda fronteira e uma decisão sobre o
        que ela serve — as duas seriam inventadas aqui."""
        assert {s.value for s in DatasetSplit} == {"REFERENCE", "EVALUATION"}

    def test_so_a_referencia_pode_alimentar_ajuste(self) -> None:
        assert DatasetSplit.REFERENCE.is_fittable
        assert not DatasetSplit.EVALUATION.is_fittable

    def test_a_impressao_muda_com_a_fronteira(self) -> None:
        outra = instant(datetime(2026, 5, 1, tzinfo=UTC))
        assert (
            FeatureDatasetSplitPolicy(reference_end_exclusive=FRONTEIRA).fingerprint
            != FeatureDatasetSplitPolicy(reference_end_exclusive=outra).fingerprint
        )

    def test_a_politica_nao_tem_onde_guardar_semente_nem_proporcao(self) -> None:
        """A propriedade é ESTRUTURAL: não é disciplina, é ausência de campo."""
        campos = set(FeatureDatasetSplitPolicy.__dataclass_fields__)
        assert campos == {"reference_end_exclusive", "name", "version"}


class TestAsContagensPorMetade:
    def test_elas_somam_o_que_receberam(self) -> None:
        contagens = (
            SplitCounts()
            .with_match(DatasetSplit.REFERENCE, rows=91)
            .with_match(DatasetSplit.REFERENCE, rows=91)
            .with_match(DatasetSplit.EVALUATION, rows=121)
        )
        assert contagens.reference_matches == 2
        assert contagens.evaluation_matches == 1
        assert contagens.reference_rows == 182
        assert contagens.evaluation_rows == 121
        assert contagens.matches == 3
        assert contagens.rows == 303

    def test_uma_metade_vazia_aparece_como_zero_e_nao_some(self) -> None:
        contagens = SplitCounts().with_match(DatasetSplit.REFERENCE, rows=91)
        assert contagens.evaluation_matches == 0
        assert contagens.as_canonical()["evaluation_rows"] == 0
