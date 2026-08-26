"""O plano de normalização — explícito, completo e versionado.

O QUE ESTES TESTES PROVAM. A parte fácil é a contagem: cento e cinco eixos,
vinte e nove robustos. A parte que importa é a CLASSIFICAÇÃO — que
`market_1x2_home_median` é reescalado e `market_1x2_home_support` não, mesmo
sendo os dois `float` no mesmo arquivo.

    cotação        preço, escala de competição       ROBUST
    nº de casas    contagem esparsa                  PASS_THROUGH

CONFUNDI-LAS É O DEFEITO QUE O PLANO EXISTE PARA IMPEDIR, e ele é invisível: uma
contagem de sete casas de apostas reescalada por mediana e IQR produz um número
perfeitamente plausível que não significa nada.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sports_intelligence.domain.features.extraction.catalog_v2 import (
    match_state_raw_space_v2,
)
from sports_intelligence.domain.features.normalized.bridge import (
    DEFAULT_INPUT_BRIDGE,
    DEFAULT_OUTPUT_ENCODING,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    FIT_SPLIT,
    NORMALIZATION_PLAN_NAME,
    NormalizationPlan,
    TransformRationale,
    TransformStrategy,
    normalization_plan_v1,
    plan_for,
    plan_summary,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import instant


@pytest.fixture(scope="module")
def plano() -> NormalizationPlan:
    return normalization_plan_v1()


class TestACobertura:
    """§11 — o plano decide sobre TODOS os eixos, e só sobre eles."""

    def test_ele_cobre_o_espaco_inteiro(self, plano: NormalizationPlan) -> None:
        plano.assert_covers(match_state_raw_space_v2())
        assert plano.size == 105

    def test_a_soma_das_duas_estrategias_e_o_espaco(self, plano: NormalizationPlan) -> None:
        assert len(plano.robust_keys) == 29
        assert len(plano.pass_through_keys) == 76
        assert len(plano.robust_keys) + len(plano.pass_through_keys) == plano.size

    def test_um_eixo_fora_do_plano_e_recusado(self, plano: NormalizationPlan) -> None:
        with pytest.raises(ValidationError, match="não decide"):
            plano.strategy_of("eixo_que_nao_existe")

    def test_um_plano_com_eixo_a_menos_nao_cobre_o_espaco(self, plano: NormalizationPlan) -> None:
        from dataclasses import replace

        incompleto = replace(plano, transforms=plano.transforms[:-1])
        with pytest.raises(ValidationError):
            incompleto.assert_covers(match_state_raw_space_v2())


class TestAClassificacaoEhSemantica:
    """§13 — a decisão vem do que a feature É, e não do tipo dela."""

    @pytest.mark.parametrize(
        ("chave", "estrategia", "razao"),
        [
            (
                "xg_home_5m",
                TransformStrategy.ROBUST_MEDIAN_IQR,
                TransformRationale.CONTINUOUS_COMPETITION_SCALED,
            ),
            (
                "shots_home_5m",
                TransformStrategy.PASS_THROUGH,
                TransformRationale.SPARSE_DISCRETE_COUNT,
            ),
        ],
    )
    def test_janelas_moveis(
        self,
        plano: NormalizationPlan,
        chave: str,
        estrategia: TransformStrategy,
        razao: TransformRationale,
    ) -> None:
        transformacao = plano.transform_of(chave)
        assert transformacao.strategy is estrategia
        assert transformacao.rationale is razao

    def test_o_preco_do_mercado_e_reescalado_e_a_contagem_de_casas_nao(
        self, plano: NormalizationPlan
    ) -> None:
        """O par que justifica o plano inteiro.

        OS DOIS SÃO `float` NO MESMO ARQUIVO. Uma regra por tipo reescalaria a
        contagem de casas de apostas — e o número resultante seria plausível.
        """
        precos = [k for k in plano.robust_keys if k.startswith("market_") and k.endswith("_median")]
        casas = [k for k in plano.pass_through_keys if k.endswith("_support")]
        assert precos, "nenhuma mediana de mercado classificada como ROBUST"
        assert casas, "nenhuma contagem de casas classificada como PASS_THROUGH"
        for chave in precos:
            assert plano.transform_of(chave).rationale is TransformRationale.MARKET_PRICE_LEVEL
        for chave in casas:
            assert plano.transform_of(chave).rationale is TransformRationale.BOOKMAKER_SUPPORT_COUNT

    def test_o_relogio_passa_direto(self, plano: NormalizationPlan) -> None:
        """O minuto do jogo é uma COORDENADA, e não uma medida.

        REESCALÁ-LO PELA MEDIANA DA COMPETIÇÃO faria «minuto 45» significar
        coisas diferentes em ligas diferentes — e a grade existe justamente
        para que ele signifique a mesma coisa em todas.
        """
        relogio = [
            t.feature_key
            for t in plano.transforms
            if t.rationale is TransformRationale.CLOCK_COORDINATE
        ]
        assert relogio
        for chave in relogio:
            assert plano.strategy_of(chave) is TransformStrategy.PASS_THROUGH

    def test_as_contagens_por_razao_sao_estaveis(self, plano: NormalizationPlan) -> None:
        assert dict(plano.rationale_counts()) == {
            "BOOKMAKER_SUPPORT_COUNT": 7,
            "CALENDAR_INTERVAL_HOURS": 3,
            "CALENDAR_MATCH_COUNT": 6,
            "CLOCK_COORDINATE": 3,
            "CONTINUOUS_COMPETITION_SCALED": 12,
            "MARKET_PRICE_DISPERSION": 7,
            "MARKET_PRICE_LEVEL": 7,
            "SPARSE_DISCRETE_COUNT": 48,
            "STRUCTURAL_MATCH_STATE": 12,
        }


class TestAIdentidadeDoPlano:
    """§16 — a impressão é o que torna duas representações comparáveis."""

    def test_ela_e_deterministica(self, plano: NormalizationPlan) -> None:
        assert normalization_plan_v1().fingerprint == plano.fingerprint

    def test_o_corte_do_ajuste_entra_na_identidade(self) -> None:
        """PR-05.1 §89 — o plano de um ajuste até junho não é o de agosto."""
        junho = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=instant(datetime(2025, 6, 1, tzinfo=UTC))
            )
        )
        agosto = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=instant(datetime(2025, 8, 1, tzinfo=UTC))
            )
        )
        assert junho.fingerprint != agosto.fingerprint
        # E AS DECISÕES SÃO AS MESMAS: o que mudou é o corte, e não a
        # classificação.
        assert junho.robust_keys == agosto.robust_keys

    def test_o_plano_declara_ajuste_sobre_referencia(self, plano: NormalizationPlan) -> None:
        assert plano.fit_split == FIT_SPLIT == "REFERENCE"
        assert plano.name == NORMALIZATION_PLAN_NAME

    def test_a_forma_canonica_volta_igual(self, plano: NormalizationPlan) -> None:
        """§ o manifesto guarda o plano DAQUELE dia, e não o de hoje."""
        de_volta = NormalizationPlan.from_canonical(plano.as_canonical())
        assert de_volta.fingerprint == plano.fingerprint
        assert de_volta.transforms == plano.transforms

    def test_as_pontes_numericas_sao_as_declaradas(self, plano: NormalizationPlan) -> None:
        assert plano.input_bridge is DEFAULT_INPUT_BRIDGE
        assert plano.output_encoding is DEFAULT_OUTPUT_ENCODING

    def test_o_resumo_legivel_existe(self, plano: NormalizationPlan) -> None:
        linhas = plan_summary(plano)
        assert linhas
        assert any("ROBUST_MEDIAN_IQR_V1" in linha for linha in linhas)


class TestOCatalogoEhFechado:
    """§14 — duas estratégias, e nenhuma terceira."""

    def test_so_duas_estrategias_existem(self) -> None:
        assert {e.value for e in TransformStrategy} == {
            "PASS_THROUGH_V1",
            "ROBUST_MEDIAN_IQR_V1",
        }

    def test_so_a_robusta_exige_artefato(self) -> None:
        assert TransformStrategy.ROBUST_MEDIAN_IQR.requires_artifact
        assert not TransformStrategy.PASS_THROUGH.requires_artifact
