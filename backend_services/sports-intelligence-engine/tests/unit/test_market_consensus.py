"""O consenso de mercado — quantis, suporte e o que cada ausência significa.

O QUE ESTES TESTES PROVAM. O método de quantil é NOSSO e é versionado (§60,
§61): eles conferem os quartis contra contas feitas à mão, e não contra o que
uma biblioteca devolve. Se alguém trocar a implementação por
`statistics.quantiles`, os números mudam e estes testes falham — que é
exatamente o ponto.

A OUTRA METADE É SEMÂNTICA DE AUSÊNCIA. Uma casa só não prova dispersão zero;
quatro casas com o mesmo preço provam. Os dois casos produzem números
parecidos e significam coisas opostas.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.market.consensus import (
    DEFAULT_IQR_SUPPORT,
    DEFAULT_MEDIAN_SUPPORT,
    MarketConsensusPolicy,
    compute_consensus,
)
from sports_intelligence.domain.features.market.specs import (
    MARKET_SPECS_V1,
    TOTAL_GOALS_LINE_V1,
    CanonicalMarketSpec,
)
from sports_intelligence.domain.features.quantiles import (
    QuantileMethod,
    QuantileSummary,
)
from sports_intelligence.domain.features.state.components import OddsState
from sports_intelligence.domain.odds.models import OddsMarket, OddsSelection
from sports_intelligence.domain.shared.errors import ValidationError
from tests.support.v2_fixtures import (
    IQR_ESPERADO,
    MEDIANA_ESPERADA,
    MERCADO_COMPLETO,
    Q1_ESPERADO,
    Q3_ESPERADO,
    quote_state,
)


def estado(*quotes: object) -> OddsState:
    return OddsState.of(tuple(quotes))  # type: ignore[arg-type]


def mercado_1x2_home() -> CanonicalMarketSpec:
    return MARKET_SPECS_V1[0]


class TestOsQuantis:
    """§57 ao §61 — o método é declarado, e conferido contra contas à mão."""

    @pytest.mark.parametrize(
        ("valores", "mediana", "q1", "q3", "iqr"),
        [
            # n=4: h = 3p. Q1 → 0,75 entre 1 e 2; Q3 → 2,25 entre 3 e 4.
            (["1", "2", "3", "4"], "2.5", "1.75", "3.25", "1.5"),
            # n=5: h = 4p. Todos os quartis caem sobre valores exatos.
            (["1", "2", "3", "4", "5"], "3", "2", "4", "2"),
            # n=1: h = 0 para qualquer p — o próprio valor.
            (["7"], "7", "7", "7", "0"),
            # n=2: h = p. Q1 → 0,25 entre os dois.
            (["10", "20"], "15", "12.5", "17.5", "5"),
            # Todos iguais: dispersão nula OBSERVADA.
            (["2.00", "2.00", "2.00", "2.00"], "2", "2", "2", "0"),
        ],
    )
    def test_os_quartis_sao_os_calculados_a_mao(
        self, valores: list[str], mediana: str, q1: str, q3: str, iqr: str
    ) -> None:
        resumo = QuantileSummary([Decimal(v) for v in valores])
        assert resumo.median == Decimal(mediana)
        assert resumo.q1 == Decimal(q1)
        assert resumo.q3 == Decimal(q3)
        assert resumo.iqr == Decimal(iqr)

    def test_o_metodo_e_declarado_e_unico(self) -> None:
        assert list(QuantileMethod) == [QuantileMethod.LINEAR_INTERPOLATED_V1]
        assert QuantileMethod.LINEAR_INTERPOLATED_V1.value == "LINEAR_INTERPOLATED_QUANTILE_V1"

    def test_a_ordem_da_entrada_nao_muda_o_quantil(self) -> None:
        direta = QuantileSummary([Decimal(v) for v in ("1", "2", "3", "4")])
        invertida = QuantileSummary([Decimal(v) for v in ("4", "3", "2", "1")])
        assert direta.median == invertida.median
        assert direta.iqr == invertida.iqr

    def test_a_aritmetica_e_decimal(self) -> None:
        """§53 — `0.1 + 0.2` não pode virar `0.30000000000000004`."""
        assert QuantileSummary([Decimal("0.1"), Decimal("0.2")]).median == Decimal("0.15")

    def test_amostra_vazia_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="amostra vazia"):
            QuantileSummary([])

    def test_quantil_fora_do_intervalo_e_recusado(self) -> None:
        resumo = QuantileSummary([Decimal(1), Decimal(2)])
        with pytest.raises(ValidationError, match="fora de"):
            resumo.quantile(Decimal("1.5"))


class TestAsEspecificacoes:
    """§46, §47, §49, §87."""

    def test_sao_sete_especificacoes(self) -> None:
        assert len(MARKET_SPECS_V1) == 7

    def test_os_tres_mercados_do_pr_estao_representados(self) -> None:
        mercados = {s.market for s in MARKET_SPECS_V1}
        assert mercados == {
            OddsMarket.MATCH_RESULT_1X2,
            OddsMarket.TOTAL_GOALS,
            OddsMarket.BOTH_TEAMS_TO_SCORE,
        }

    def test_o_handicap_nao_entra(self) -> None:
        """§49 — a linha varia por jogo, e fixar uma produziria coluna vazia."""
        assert OddsMarket.ASIAN_HANDICAP not in {s.market for s in MARKET_SPECS_V1}

    def test_o_mercado_de_gols_carrega_a_linha(self) -> None:
        totals = [s for s in MARKET_SPECS_V1 if s.market is OddsMarket.TOTAL_GOALS]
        assert len(totals) == 2
        assert all(s.line == TOTAL_GOALS_LINE_V1 for s in totals)
        assert all(s.line_text == "2.5" for s in totals)

    def test_selecao_incompativel_com_o_mercado_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="não admite a seleção"):
            CanonicalMarketSpec(
                key_fragment="x",
                market=OddsMarket.TOTAL_GOALS,
                selection=OddsSelection.DRAW,
                line=Decimal("2.5"),
            )

    def test_mercado_que_exige_linha_sem_linha_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="exige linha"):
            CanonicalMarketSpec(
                key_fragment="x",
                market=OddsMarket.TOTAL_GOALS,
                selection=OddsSelection.OVER,
            )

    def test_linha_num_mercado_que_nao_a_usa_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="não usa linha"):
            CanonicalMarketSpec(
                key_fragment="x",
                market=OddsMarket.BOTH_TEAMS_TO_SCORE,
                selection=OddsSelection.YES,
                line=Decimal("2.5"),
            )

    def test_a_linha_faz_parte_do_casamento(self) -> None:
        over = next(s for s in MARKET_SPECS_V1 if s.key_fragment == "totals_over_25")
        assert over.matches(market="TOTAL_GOALS", selection="OVER", line="2.5")
        assert not over.matches(market="TOTAL_GOALS", selection="OVER", line="3.5")


class TestOConsenso:
    def test_quatro_casas_dao_mediana_iqr_e_suporte(self) -> None:
        odds = estado(
            *(quote_state(f"CASA{n}", valor) for n, valor in enumerate(MERCADO_COMPLETO, start=1))
        )
        consenso = compute_consensus(odds, mercado_1x2_home(), policy=MarketConsensusPolicy())
        assert consenso.support == 4
        assert consenso.median == MEDIANA_ESPERADA
        assert consenso.q1 == Q1_ESPERADO
        assert consenso.q3 == Q3_ESPERADO
        assert consenso.iqr == IQR_ESPERADO

    def test_uma_casa_da_mediana_e_nao_da_dispersao(self) -> None:
        """§62, §69 — uma cotação não prova que o mercado é unânime."""
        odds = estado(quote_state("CASA1", "2.00"))
        consenso = compute_consensus(odds, mercado_1x2_home(), policy=MarketConsensusPolicy())
        assert consenso.support == 1
        assert consenso.median == Decimal("2")
        assert consenso.iqr is None

    def test_quatro_casas_iguais_dao_dispersao_zero_observada(self) -> None:
        """§70 — aqui o zero é um FATO sobre o mercado."""
        odds = estado(*(quote_state(f"CASA{n}", "2.00") for n in range(1, 5)))
        consenso = compute_consensus(odds, mercado_1x2_home(), policy=MarketConsensusPolicy())
        assert consenso.iqr == Decimal(0)
        assert consenso.support == 4

    def test_a_ordem_das_casas_nao_muda_nada(self) -> None:
        """§169, §170 — nada depende da ordem do banco."""
        direta = estado(
            *(quote_state(f"CASA{n}", valor) for n, valor in enumerate(MERCADO_COMPLETO, start=1))
        )
        invertida = estado(
            *reversed(
                [
                    quote_state(f"CASA{n}", valor)
                    for n, valor in enumerate(MERCADO_COMPLETO, start=1)
                ]
            )
        )
        politica = MarketConsensusPolicy()
        a = compute_consensus(direta, mercado_1x2_home(), policy=politica)
        b = compute_consensus(invertida, mercado_1x2_home(), policy=politica)
        assert (a.median, a.iqr, a.support) == (b.median, b.iqr, b.support)
        assert [q.bookmaker for q in a.quotes] == [q.bookmaker for q in b.quotes]

    def test_um_mercado_sem_cotacao_nao_tem_consenso(self) -> None:
        odds = estado(quote_state("CASA1", "2.00"))
        btts = next(s for s in MARKET_SPECS_V1 if s.key_fragment == "btts_yes")
        consenso = compute_consensus(odds, btts, policy=MarketConsensusPolicy())
        assert not consenso.has_quotes
        assert consenso.median is None
        assert consenso.support == 0

    def test_cotacoes_de_outra_selecao_nao_entram(self) -> None:
        odds = estado(
            quote_state("CASA1", "2.00", selection="HOME"),
            quote_state("CASA1", "3.40", selection="DRAW"),
        )
        consenso = compute_consensus(odds, mercado_1x2_home(), policy=MarketConsensusPolicy())
        assert consenso.support == 1
        assert consenso.median == Decimal("2")

    def test_cotacoes_de_outra_linha_nao_entram(self) -> None:
        """§87 — `over 2.5` e `over 3.5` são mercados diferentes."""
        over = next(s for s in MARKET_SPECS_V1 if s.key_fragment == "totals_over_25")
        odds = estado(
            quote_state("CASA1", "1.90", market="TOTAL_GOALS", selection="OVER", line="2.5"),
            quote_state("CASA1", "3.10", market="TOTAL_GOALS", selection="OVER", line="3.5"),
        )
        consenso = compute_consensus(odds, over, policy=MarketConsensusPolicy())
        assert consenso.support == 1
        assert consenso.median == Decimal("1.9")

    def test_cotacao_nao_positiva_e_recusada(self) -> None:
        """§68 — cotação decimal zero não existe no domínio."""
        odds = estado(quote_state("CASA1", "0"))
        with pytest.raises(ValidationError, match="não admite zero"):
            compute_consensus(odds, mercado_1x2_home(), policy=MarketConsensusPolicy())


class TestAPolitica:
    """§64 — versionada e impressa."""

    def test_os_limiares_padrao_sao_os_declarados(self) -> None:
        politica = MarketConsensusPolicy()
        assert politica.median_minimum_support == DEFAULT_MEDIAN_SUPPORT == 1
        assert politica.iqr_minimum_support == DEFAULT_IQR_SUPPORT == 4

    def test_a_impressao_muda_com_o_limiar(self) -> None:
        assert (
            MarketConsensusPolicy(iqr_minimum_support=6).fingerprint
            != MarketConsensusPolicy().fingerprint
        )

    def test_a_impressao_e_estavel(self) -> None:
        assert MarketConsensusPolicy().fingerprint == MarketConsensusPolicy().fingerprint

    def test_suporte_de_iqr_abaixo_do_de_mediana_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="abaixo do suporte da"):
            MarketConsensusPolicy(median_minimum_support=4, iqr_minimum_support=2)

    def test_suporte_de_mediana_zero_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="abaixo de 1"):
            MarketConsensusPolicy(median_minimum_support=0)

    def test_o_limiar_de_iqr_e_respeitado(self) -> None:
        odds = estado(*(quote_state(f"CASA{n}", f"2.0{n}") for n in range(1, 6)))
        estrita = MarketConsensusPolicy(iqr_minimum_support=6)
        consenso = compute_consensus(odds, mercado_1x2_home(), policy=estrita)
        assert consenso.support == 5
        assert consenso.median is not None
        assert consenso.iqr is None


class TestAsFeaturesDeMercado:
    """As vinte e uma dimensões, vistas pelo snapshot."""

    def test_o_mercado_completo_produz_os_tres_numeros(self) -> None:
        from tests.support.v2_fixtures import extrair_v2

        snapshot = extrair_v2()
        assert snapshot.value_of("market_1x2_home_median").numeric == float(MEDIANA_ESPERADA)
        assert snapshot.value_of("market_1x2_home_iqr").numeric == float(IQR_ESPERADO)
        assert snapshot.value_of("market_1x2_home_support").numeric == 4

    def test_uma_casa_da_mediana_e_suporte_e_nao_da_iqr(self) -> None:
        from tests.support.v2_fixtures import extrair_v2

        snapshot = extrair_v2()
        assert snapshot.value_of("market_btts_yes_median").numeric == 1.7
        assert snapshot.value_of("market_btts_yes_support").numeric == 1
        iqr = snapshot.value_of("market_btts_yes_iqr")
        assert not iqr.is_available
        assert iqr.availability is FeatureAvailability.INSUFFICIENT_COVERAGE

    def test_mercado_sem_cotacao_e_fonte_indisponivel(self) -> None:
        """§66 — `ODDS` publicada, e ESTE mercado não veio."""
        from tests.support.v2_fixtures import extrair_v2

        snapshot = extrair_v2()
        draw = snapshot.value_of("market_1x2_draw_median")
        assert not draw.is_available
        assert draw.availability is FeatureAvailability.SOURCE_UNAVAILABLE

    def test_sem_a_familia_odds_tudo_e_nao_declarado(self) -> None:
        from tests.support.snapshot_fixtures import TODAS_AS_FAMILIAS
        from tests.support.v2_fixtures import entrada_v2, extrair_v2

        snapshot = extrair_v2(
            entrada_v2(families=TODAS_AS_FAMILIAS, odds=()),
            families=TODAS_AS_FAMILIAS,
        )
        for chave in (
            "market_1x2_home_median",
            "market_1x2_home_iqr",
            "market_1x2_home_support",
        ):
            computada = snapshot.value_of(chave)
            assert computada.availability is FeatureAvailability.NOT_DECLARED
            assert computada.numeric is None

    def test_a_procedencia_aponta_as_cotacoes_usadas(self) -> None:
        """§71."""
        from tests.support.v2_fixtures import extrair_v2

        procedencia = extrair_v2().value_of("market_1x2_home_median").provenance
        assert procedencia.count == 4
        assert {c.kind for c in procedencia.sample} == {"ODDS"}

    def test_a_casa_de_aposta_nao_aparece_no_espaco(self) -> None:
        """§72, §45 — a dimensão não pode depender de quantas casas existem."""
        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            match_state_raw_space_v2,
        )

        chaves = match_state_raw_space_v2().keys
        assert not [k for k in chaves if "casa" in k or "bet365" in k.lower()]
