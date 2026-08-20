"""O contexto pré-jogo — calendário, fronteiras e a prova de cobertura.

O QUE ESTES TESTES PROVAM. Três coisas, e a terceira é a que mais custa quando
falta:

    1. os NÚMEROS — intervalo e contagens, contra contas feitas à mão
    2. as FRONTEIRAS — a partida exatamente em `T-14d` entra; a atual nunca
    3. a COBERTURA — «zero partidas» e «o corpus começa aqui» produzem o mesmo
       número e significam coisas opostas

A terceira é o caso da primeira rodada de qualquer corpus. Sem ela, todo time
apareceria como tendo descansado o mês inteiro no começo do arquivo — e o
modelo aprenderia que quem joga a primeira rodada está sempre descansado.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.prematch.models import (
    ContextCoverage,
    MatchContextInput,
    PriorMatchRef,
    TeamPriorMatches,
    team_prior_matches,
)
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
    ContextScope,
    HistoricalContextPolicy,
    PriorMatchEligibility,
    WindowBoundary,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import instant
from tests.support.feature_fixtures import CASA, FORA, PARTIDA
from tests.support.v2_fixtures import (
    COMPETICAO,
    GAP_ESPERADO_CASA,
    GAP_ESPERADO_FORA,
    KICKOFF_A,
    KICKOFF_ATUAL,
    KICKOFF_C,
    MATCH_A,
    MATCH_C,
    cobertura,
    contexto_de_partida,
    extrair_v2,
)


class TestAPolitica:
    """§17 — versionada, impressa, e com o escopo recusado explicitamente."""

    def test_o_padrao_e_local_a_competicao(self) -> None:
        politica = DEFAULT_CONTEXT_POLICY
        assert politica.scope is ContextScope.SAME_COMPETITION
        assert politica.eligibility is PriorMatchEligibility.PUBLISHED_RESULT
        assert politica.lookback_days == (14, 30)
        assert politica.boundary is WindowBoundary.CLOSED_OPEN

    def test_o_escopo_cruzado_e_recusado(self) -> None:
        """§13, §15 — a V1 não cruza competições, e o tipo diz por quê."""
        with pytest.raises(ValidationError, match="ALL_COMPETITIONS"):
            HistoricalContextPolicy(scope=ContextScope.ALL_COMPETITIONS)

    def test_janelas_fora_de_ordem_sao_recusadas(self) -> None:
        with pytest.raises(ValidationError, match="fora de ordem"):
            HistoricalContextPolicy(lookback_days=(30, 14))

    def test_janela_repetida_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="fora de ordem"):
            HistoricalContextPolicy(lookback_days=(14, 14))

    def test_a_impressao_muda_com_a_janela(self) -> None:
        assert (
            HistoricalContextPolicy(lookback_days=(7, 30)).fingerprint
            != DEFAULT_CONTEXT_POLICY.fingerprint
        )

    def test_a_impressao_e_estavel(self) -> None:
        assert (
            HistoricalContextPolicy().fingerprint == HistoricalContextPolicy().fingerprint
        )

    def test_o_maior_retrospecto_orienta_a_leitura(self) -> None:
        assert DEFAULT_CONTEXT_POLICY.max_lookback_days == 30


class TestOsInsumos:
    def test_as_anteriores_ficam_em_ordem_crescente(self) -> None:
        historico = team_prior_matches(
            CASA,
            [
                PriorMatchRef(kickoff=KICKOFF_C, match_id=MATCH_C),
                PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_A),
            ],
        )
        assert [m.match_id for m in historico.matches] == [MATCH_A, MATCH_C]
        assert historico.latest is not None
        assert historico.latest.match_id == MATCH_C

    def test_lista_fora_de_ordem_no_construtor_direto_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="fora de ordem"):
            TeamPriorMatches(
                team_id=CASA,
                matches=(
                    PriorMatchRef(kickoff=KICKOFF_C, match_id=MATCH_C),
                    PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_A),
                ),
            )

    def test_partida_anterior_repetida_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="repetida"):
            team_prior_matches(
                CASA,
                [
                    PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_A),
                    PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_A),
                ],
            )

    def test_sem_anteriores_nao_ha_ultima(self) -> None:
        assert team_prior_matches(CASA, []).latest is None

    def test_duas_partidas_no_mesmo_instante_sao_ordenaveis(self) -> None:
        """Uma rodada inteira começa às 15:00 — o caso é a regra, e não a exceção.

        Sem desempate textual, a ordenação cairia no `MatchId`, que não tem
        ordem total. O defeito só aparece quando duas anteriores do MESMO time
        coincidem no relógio — o que num corpus de dez mil partidas acontece.
        """
        historico = team_prior_matches(
            CASA,
            [
                PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_C),
                PriorMatchRef(kickoff=KICKOFF_A, match_id=MATCH_A),
            ],
        )
        assert historico.latest is not None
        assert len(historico.matches) == 2
        # O desempate é o TEXTO do id: estável entre execuções, e sem
        # significado esportivo nenhum.
        assert [m.match_id for m in historico.matches] == sorted(
            (MATCH_A, MATCH_C), key=str
        )

    def test_uma_partida_futura_no_contexto_e_recusada(self) -> None:
        """§29, §164 — ela produziria carga que ninguém tinha no apito."""
        futura = instant(datetime(2026, 4, 5, 12, 0, tzinfo=UTC))
        with pytest.raises(ValidationError, match="depois do próprio"):
            MatchContextInput(
                match_id=PARTIDA,
                competition_id=COMPETICAO,
                kickoff=KICKOFF_ATUAL,
                home=team_prior_matches(
                    CASA,
                    [PriorMatchRef(kickoff=futura, match_id=MATCH_A)],
                ),
                away=team_prior_matches(FORA, []),
                coverage=cobertura(),
            )

    def test_a_propria_partida_no_contexto_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match=r"próprio contexto|depois do próprio"):
            MatchContextInput(
                match_id=PARTIDA,
                competition_id=COMPETICAO,
                kickoff=KICKOFF_ATUAL,
                home=team_prior_matches(
                    CASA, [PriorMatchRef(kickoff=KICKOFF_A, match_id=PARTIDA)]
                ),
                away=team_prior_matches(FORA, []),
                coverage=cobertura(),
            )

    def test_cobertura_de_outra_competicao_e_recusada(self) -> None:
        from sports_intelligence.domain.shared.identity import CompetitionId

        outra = CompetitionId.derive("pr054", "outra-competicao")
        with pytest.raises(ValidationError, match="cobertura é da competição"):
            MatchContextInput(
                match_id=PARTIDA,
                competition_id=COMPETICAO,
                kickoff=KICKOFF_ATUAL,
                home=team_prior_matches(CASA, []),
                away=team_prior_matches(FORA, []),
                coverage=ContextCoverage(competition_id=outra),
            )


class TestAJanela:
    """§28, §29, §30 — `[T-w, T)`, fechada no início e aberta no fim."""

    def _historico(self, *instantes: object) -> TeamPriorMatches:
        return team_prior_matches(
            CASA,
            [
                PriorMatchRef(
                    kickoff=k,  # type: ignore[arg-type]
                    match_id=MatchId.derive("pr054-janela", str(n)),
                )
                for n, k in enumerate(instantes)
            ],
        )

    def test_a_partida_exatamente_em_t_menos_w_entra(self) -> None:
        """§30 — o início é INCLUSIVO."""
        inicio = KICKOFF_ATUAL - timedelta(days=14)
        historico = self._historico(inicio)
        assert len(historico.within(start=inicio, end=KICKOFF_ATUAL)) == 1

    def test_um_segundo_antes_de_t_menos_w_fica_de_fora(self) -> None:
        inicio = KICKOFF_ATUAL - timedelta(days=14)
        historico = self._historico(inicio - timedelta(seconds=1))
        assert historico.within(start=inicio, end=KICKOFF_ATUAL) == ()

    def test_a_partida_exatamente_em_t_fica_de_fora(self) -> None:
        """§29 — o fim é EXCLUSIVO, e a partida atual nunca entra."""
        inicio = KICKOFF_ATUAL - timedelta(days=14)
        historico = self._historico(KICKOFF_ATUAL - timedelta(seconds=1))
        assert len(historico.within(start=inicio, end=KICKOFF_ATUAL)) == 1


class TestACobertura:
    """§32, §33, §34 — a prova de que o corpus alcança a janela."""

    def test_o_corpus_que_alcanca_o_inicio_cobre(self) -> None:
        assert cobertura(alcanca=KICKOFF_A).covers(start=KICKOFF_A)

    def test_o_corpus_que_comeca_depois_nao_cobre(self) -> None:
        assert not cobertura(alcanca=KICKOFF_C).covers(start=KICKOFF_A)

    def test_sem_primeira_partida_conhecida_nada_e_afirmavel(self) -> None:
        """FAIL-CLOSED — a versão não publica partida daquela competição."""
        assert not cobertura(alcanca=None).covers(start=KICKOFF_A)


class TestAsFeaturesDeContexto:
    """Os nove valores, conferidos contra a tabela do cenário."""

    def test_o_intervalo_ate_a_anterior_e_o_calculado_a_mao(self) -> None:
        """C em 22/03 12:00 → atual em 29/03 15:00 = 171 horas."""
        snapshot = extrair_v2()
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_home").numeric == float(
            GAP_ESPERADO_CASA
        )
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_away").numeric == float(
            GAP_ESPERADO_FORA
        )

    def test_a_diferenca_de_intervalo_e_casa_menos_fora(self) -> None:
        snapshot = extrair_v2()
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_diff").numeric == float(
            GAP_ESPERADO_CASA - GAP_ESPERADO_FORA
        )

    def test_a_contagem_de_catorze_dias(self) -> None:
        """[15/03 15:00, 29/03 15:00) contém só C, dos 22/03."""
        snapshot = extrair_v2()
        assert snapshot.value_of("ctx_same_comp_matches_14d_home").numeric == 1
        assert snapshot.value_of("ctx_same_comp_matches_14d_away").numeric == 0
        assert snapshot.value_of("ctx_same_comp_matches_14d_diff").numeric == 1

    def test_a_contagem_de_trinta_dias(self) -> None:
        """[27/02 15:00, 29/03 15:00) contém A, B e C."""
        snapshot = extrair_v2()
        assert snapshot.value_of("ctx_same_comp_matches_30d_home").numeric == 3
        assert snapshot.value_of("ctx_same_comp_matches_30d_away").numeric == 1
        assert snapshot.value_of("ctx_same_comp_matches_30d_diff").numeric == 2

    def test_zero_partidas_com_cobertura_provada_e_disponivel(self) -> None:
        """§31 — zero OBSERVADO é um fato."""
        computada = extrair_v2().value_of("ctx_same_comp_matches_14d_away")
        assert computada.is_available
        assert computada.numeric == 0

    def test_sem_cobertura_a_contagem_nao_e_zero(self) -> None:
        """§32, §33, §34 — o corpus começa depois do início da janela."""
        snapshot = extrair_v2(
            contexto=contexto_de_partida(coverage=cobertura(alcanca=KICKOFF_C))
        )
        computada = snapshot.value_of("ctx_same_comp_matches_30d_home")
        assert not computada.is_available
        assert computada.availability is FeatureAvailability.INSUFFICIENT_COVERAGE
        assert computada.numeric is None

    def test_sem_partida_anterior_o_intervalo_nao_e_zero(self) -> None:
        """§26 — «não jogou antes» não é «jogou agora há pouco»."""
        snapshot = extrair_v2(contexto=contexto_de_partida(casa=(), fora=()))
        computada = snapshot.value_of("ctx_same_comp_prev_gap_hours_home")
        assert not computada.is_available
        assert computada.numeric is None

    def test_sem_anterior_e_sem_cobertura_o_motivo_e_a_cobertura(self) -> None:
        """§33 — a borda do corpus é diagnóstico diferente do calendário."""
        snapshot = extrair_v2(
            contexto=contexto_de_partida(
                casa=(), fora=(), coverage=cobertura(alcanca=None)
            )
        )
        computada = snapshot.value_of("ctx_same_comp_prev_gap_hours_home")
        assert computada.availability is FeatureAvailability.INSUFFICIENT_COVERAGE

    def test_sem_anterior_e_com_cobertura_o_motivo_e_a_fonte(self) -> None:
        snapshot = extrair_v2(contexto=contexto_de_partida(casa=(), fora=()))
        computada = snapshot.value_of("ctx_same_comp_prev_gap_hours_home")
        assert computada.availability is FeatureAvailability.SOURCE_UNAVAILABLE

    def test_um_lado_indisponivel_torna_a_diferenca_indisponivel(self) -> None:
        """§25, §65."""
        snapshot = extrair_v2(contexto=contexto_de_partida(fora=()))
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_home").is_available
        assert not snapshot.value_of("ctx_same_comp_prev_gap_hours_away").is_available
        assert not snapshot.value_of("ctx_same_comp_prev_gap_hours_diff").is_available

    def test_sem_contexto_nenhum_as_nove_ficam_indisponiveis(self) -> None:
        """§82 — a leitura não trouxe contexto, e isso não é zero."""
        snapshot = extrair_v2(sem_contexto=True)
        for chave in (
            "ctx_same_comp_prev_gap_hours_home",
            "ctx_same_comp_matches_14d_home",
            "ctx_same_comp_matches_30d_diff",
        ):
            computada = snapshot.value_of(chave)
            assert not computada.is_available, chave
            assert computada.numeric is None, chave

    def test_a_procedencia_aponta_as_partidas_anteriores(self) -> None:
        """§35."""
        snapshot = extrair_v2()
        intervalo = snapshot.value_of("ctx_same_comp_prev_gap_hours_home").provenance
        assert intervalo.count == 1
        assert intervalo.sample[0].reference == str(MATCH_C)
        contagem = snapshot.value_of("ctx_same_comp_matches_30d_home").provenance
        assert contagem.count == 3
        assert {c.kind for c in contagem.sample} == {"MATCH"}

    def test_o_intervalo_e_decimal_e_nao_acumula_erro(self) -> None:
        """§24 — horas exatas, e não float incidental."""
        meia_hora = KICKOFF_ATUAL - timedelta(minutes=30)
        snapshot = extrair_v2(
            contexto=contexto_de_partida(casa=((meia_hora, MATCH_A),))
        )
        assert snapshot.value_of("ctx_same_comp_prev_gap_hours_home").numeric == 0.5

    def test_as_features_de_contexto_sao_pre_jogo(self) -> None:
        """§22 — elas não dependem do corte."""
        from sports_intelligence.domain.features.definitions import (
            FeatureTemporalClass,
        )
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            extended_feature_catalog,
        )

        catalogo = extended_feature_catalog()
        for chave in ("ctx_same_comp_prev_gap_hours_home", "ctx_same_comp_matches_14d_home"):
            definicao = catalogo.spec_of(chave).definition
            assert definicao.temporal_class is FeatureTemporalClass.PRE_MATCH

    def test_a_politica_entra_na_impressao_da_feature(self) -> None:
        """§84 — trocar o escopo mudaria o que a feature mede."""
        from sports_intelligence.domain.features.extraction.catalog import FeatureSide
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            ContextFeatureKind,
            context_definition,
        )

        padrao = context_definition(
            kind=ContextFeatureKind.MATCHES_IN_WINDOW,
            side=FeatureSide.HOME,
            policy=DEFAULT_CONTEXT_POLICY,
            lookback_days=14,
        )
        outra = context_definition(
            kind=ContextFeatureKind.MATCHES_IN_WINDOW,
            side=FeatureSide.HOME,
            policy=HistoricalContextPolicy(
                eligibility=PriorMatchEligibility.KICKOFF_BEFORE
            ),
            lookback_days=14,
        )
        assert padrao.key == outra.key
        assert padrao.fingerprint != outra.fingerprint


class TestOIntervaloEmHoras:
    """A conta, isolada do resto."""

    @pytest.mark.parametrize(
        ("delta", "esperado"),
        [
            (timedelta(hours=1), "1"),
            (timedelta(days=1), "24"),
            (timedelta(days=7, hours=3), "171"),
            (timedelta(minutes=90), "1.5"),
        ],
    )
    def test_o_intervalo_e_o_esperado(self, delta: timedelta, esperado: str) -> None:
        anterior = KICKOFF_ATUAL - delta
        snapshot = extrair_v2(
            contexto=contexto_de_partida(casa=((anterior, MATCH_A),))
        )
        assert snapshot.value_of(
            "ctx_same_comp_prev_gap_hours_home"
        ).numeric == float(Decimal(esperado))
