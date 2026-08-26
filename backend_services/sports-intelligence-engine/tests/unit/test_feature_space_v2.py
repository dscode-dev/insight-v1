"""A V2 — e a prova de que a V1 não foi tocada.

O TESTE MAIS IMPORTANTE DESTE ARQUIVO é o mais curto: a impressão dourada da
V1 continua exatamente a mesma (§90, §175, §219). Um espaço que ganhasse trinta
dimensões mantendo o número da versão faria todo snapshot histórico comparar
com um espaço que não é o dele — e a comparação não falharia, mentiria.

O SEGUNDO é a compatibilidade de prefixo (§8, §157): as setenta e cinco
primeiras definições da V2 são as MESMAS da V1 — os mesmos objetos, não cópias
equivalentes. Isso torna a comparação entre versões trivial e torna impossível
uma delas divergir por edição.
"""

from __future__ import annotations

from typing import Final

import pytest

from sports_intelligence.domain.features.definitions import FeatureTemporalClass
from sports_intelligence.domain.features.extraction.catalog import (
    match_state_raw_space_v1,
    production_feature_catalog,
)
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    MATCH_STATE_RAW_V2_NAME,
    V1_SIZE,
    ContextFeatureSpec,
    MarketFeatureSpec,
    extended_feature_catalog,
    extended_feature_registry,
    match_state_raw_space_v2,
    v1_catalog_view,
)
from sports_intelligence.domain.features.market.specs import MARKET_SPECS_V1
from sports_intelligence.domain.features.prematch.policy import (
    DEFAULT_CONTEXT_POLICY,
    HistoricalContextPolicy,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from tests.unit.test_feature_catalog import GOLDEN_SPACE

#: A impressão DOURADA da V2 (§91).
GOLDEN_SPACE_V2: Final[str] = "9ab9b3222f9997a272d3dbde25b18698a1807092a0c6278382eb8a25194f266a"

#: As impressões douradas das definições NOVAS (§92): uma de intervalo, duas de
#: contagem — incluindo a diferença —, e uma de cada dimensão de mercado.
GOLDEN_V2_FEATURES: Final[dict[str, str]] = {
    "ctx_same_comp_prev_gap_hours_home": (
        "0c038f508ae0b3d2210b9d6977db4edab180b66e8a64caed8dc1015a10960450"
    ),
    "ctx_same_comp_matches_14d_home": (
        "84b67180b76c2ea986135ee2892544c7a806f00d3f267060863f4bf19b1afd6e"
    ),
    "ctx_same_comp_matches_30d_diff": (
        "e17cc125038e451d1e00011b60dd2caaf5d6f6e3ce23f035d8e1caf7d1fb6a28"
    ),
    "market_1x2_home_median": ("6a380b1a87308de4eba916fbf6c545c1c322d0c29aae3b36ba981decdca73112"),
    "market_totals_over_25_iqr": (
        "91aa2accb602af4a3d337b8f6655307f5d1dffc53ef13ea40c6a308ca8f5322a"
    ),
    "market_btts_yes_support": ("f09264e3f70814a8cf5405d25f26bede73b4332de8826b26e4a07d757f3dcc35"),
}

TOTAL_V2: Final[int] = 105
CONTEXTO: Final[int] = 9
MERCADO: Final[int] = 21


class TestAV1ContinuaIntacta:
    """§3, §5, §90, §175, §219 — a regra absoluta deste PR."""

    def test_a_impressao_dourada_da_v1_nao_mudou(self) -> None:
        assert match_state_raw_space_v1().fingerprint == GOLDEN_SPACE

    def test_a_v1_continua_com_setenta_e_cinco_definicoes(self) -> None:
        assert production_feature_catalog().size == V1_SIZE == 75
        assert match_state_raw_space_v1().size == 75

    def test_a_v1_continua_na_versao_um(self) -> None:
        assert str(match_state_raw_space_v1().version) == "v1.0"

    def test_a_v1_continua_exigindo_o_que_exigia(self) -> None:
        requisito = match_state_raw_space_v1().requirement
        assert set(requisito.families) == {CoverageFamily.EVENT, CoverageFamily.LINEUP}
        assert requisito.optional_families == ()

    def test_a_v1_e_carregavel_pelo_registro(self) -> None:
        """§5 — o registro continua conseguindo carregar as mesmas 75."""
        registro = extended_feature_registry()
        for definicao in production_feature_catalog().definitions:
            assert registro.get(definicao.key, str(definicao.version)) == definicao


class TestAV2:
    """§4, §6, §88."""

    def test_o_nome_e_a_versao_sao_os_declarados(self) -> None:
        espaco = match_state_raw_space_v2()
        assert espaco.name == MATCH_STATE_RAW_V2_NAME
        assert str(espaco.version) == "v2.0"

    def test_a_contagem_e_setenta_e_cinco_mais_trinta(self) -> None:
        """§88 — 75 herdadas + 9 de contexto + 21 de mercado."""
        catalogo = extended_feature_catalog()
        assert catalogo.size == TOTAL_V2 == 105
        contexto = [s for s in catalogo.specs if isinstance(s, ContextFeatureSpec)]
        mercado = [s for s in catalogo.specs if isinstance(s, MarketFeatureSpec)]
        assert len(contexto) == CONTEXTO
        assert len(mercado) == MERCADO == len(MARKET_SPECS_V1) * 3

    def test_a_impressao_dourada_da_v2(self) -> None:
        """§91."""
        assert match_state_raw_space_v2().fingerprint == GOLDEN_SPACE_V2

    def test_a_impressao_da_v2_difere_da_v1(self) -> None:
        assert match_state_raw_space_v2().fingerprint != GOLDEN_SPACE

    def test_a_v2_continua_crua(self) -> None:
        """§152 — nenhuma definição declara normalizador."""
        com_normalizador = [
            d.key for d in extended_feature_catalog().definitions if d.normalizer_key is not None
        ]
        assert com_normalizador == []

    def test_toda_definicao_nova_declara_unidade(self) -> None:
        catalogo = extended_feature_catalog()
        novas = catalogo.definitions[catalogo.inherited :]
        assert [d.key for d in novas if not d.unit] == []

    def test_o_registro_carrega_as_cento_e_cinco(self) -> None:
        """§89."""
        assert len(extended_feature_registry()) == TOTAL_V2


class TestACompatibilidadeDePrefixo:
    """§8, §157 — `V2[0:75] == V1`, e não «equivalente»."""

    def test_as_chaves_do_prefixo_sao_as_da_v1(self) -> None:
        assert match_state_raw_space_v2().keys[:V1_SIZE] == match_state_raw_space_v1().keys

    def test_as_definicoes_do_prefixo_sao_OS_MESMOS_objetos(self) -> None:
        prefixo = extended_feature_catalog().definitions[:V1_SIZE]
        assert prefixo == production_feature_catalog().definitions

    def test_as_impressoes_do_prefixo_sao_as_da_v1(self) -> None:
        v1 = {d.key: d.fingerprint for d in production_feature_catalog().definitions}
        for definicao in extended_feature_catalog().definitions[:V1_SIZE]:
            assert definicao.fingerprint == v1[definicao.key]

    def test_a_visao_v1_do_catalogo_estendido_e_a_v1(self) -> None:
        """§156 — o extrator da V1 recebe o catálogo da V1, e não uma fatia."""
        visao = v1_catalog_view(extended_feature_catalog())
        assert visao.definitions == production_feature_catalog().definitions

    def test_um_prefixo_alterado_e_recusado(self) -> None:
        """A guarda estrutural: a V2 não pode reescrever uma feature da V1."""
        from dataclasses import replace

        from sports_intelligence.domain.features.extraction.catalog_v2 import (
            ExtendedFeatureCatalog,
        )

        catalogo = extended_feature_catalog()
        primeira = catalogo.specs[0]
        adulterada = replace(
            primeira,
            definition=replace(primeira.definition, unit="adulterada"),
        )
        with pytest.raises(ValidationError, match="APPEND"):
            ExtendedFeatureCatalog(specs=(adulterada, *catalogo.specs[1:]))


class TestOsDouradosDaV2:
    """§92 — mudar uma destas exige decidir sobre versão."""

    @pytest.mark.parametrize(("chave", "esperada"), sorted(GOLDEN_V2_FEATURES.items()))
    def test_a_impressao_da_definicao_e_a_dourada(self, chave: str, esperada: str) -> None:
        assert extended_feature_catalog().spec_of(chave).definition.fingerprint == esperada


class TestAOrdemDaV2:
    """§7, §74 — declarada, e não alfabética."""

    def test_o_contexto_vem_antes_do_mercado(self) -> None:
        chaves = match_state_raw_space_v2().keys
        primeiro_contexto = next(i for i, k in enumerate(chaves) if k.startswith("ctx_"))
        primeiro_mercado = next(i for i, k in enumerate(chaves) if k.startswith("market_"))
        assert V1_SIZE <= primeiro_contexto < primeiro_mercado

    def test_o_intervalo_vem_antes_das_contagens(self) -> None:
        chaves = list(match_state_raw_space_v2().keys)
        assert chaves.index("ctx_same_comp_prev_gap_hours_home") < chaves.index(
            "ctx_same_comp_matches_14d_home"
        )
        assert chaves.index("ctx_same_comp_matches_14d_home") < chaves.index(
            "ctx_same_comp_matches_30d_home"
        )

    def test_cada_mercado_traz_mediana_iqr_e_suporte_nessa_ordem(self) -> None:
        chaves = list(match_state_raw_space_v2().keys)
        base = chaves.index("market_1x2_home_median")
        assert chaves[base : base + 3] == [
            "market_1x2_home_median",
            "market_1x2_home_iqr",
            "market_1x2_home_support",
        ]

    def test_a_ordem_nao_e_alfabetica(self) -> None:
        chaves = match_state_raw_space_v2().keys
        assert list(chaves) != sorted(chaves)


class TestAsExigenciasDaV2:
    """§80, §81, §82 — o que inviabiliza e o que só some da máscara."""

    def test_event_e_lineup_continuam_obrigatorias(self) -> None:
        requisito = match_state_raw_space_v2().requirement
        assert CoverageFamily.EVENT in requisito.families
        assert CoverageFamily.LINEUP in requisito.families

    def test_odds_e_opcional(self) -> None:
        """§80 — um corpus sem mercado ainda produz snapshot."""
        requisito = match_state_raw_space_v2().requirement
        assert CoverageFamily.ODDS in requisito.optional_families
        assert CoverageFamily.ODDS not in requisito.families

    def test_um_corpus_sem_odds_e_compativel(self) -> None:
        match_state_raw_space_v2().assert_compatible_with(
            frozenset({CoverageFamily.EVENT, CoverageFamily.LINEUP, CoverageFamily.MATCH})
        )

    def test_um_corpus_sem_event_nao_e_compativel(self) -> None:
        with pytest.raises(ValidationError, match="EVENT"):
            match_state_raw_space_v2().assert_compatible_with(frozenset({CoverageFamily.MATCH}))

    def test_familia_obrigatoria_e_opcional_ao_mesmo_tempo_e_recusada(self) -> None:
        from sports_intelligence.domain.features.space import CorpusRequirement

        with pytest.raises(ValidationError, match="obrigatória E opcional"):
            CorpusRequirement.of(CoverageFamily.ODDS, optional=(CoverageFamily.ODDS,))

    def test_requisito_sem_opcionais_produz_o_documento_antigo(self) -> None:
        """A garantia que preserva a impressão da V1."""
        from sports_intelligence.domain.features.space import CorpusRequirement

        requisito = CorpusRequirement.of(CoverageFamily.EVENT)
        assert requisito.as_canonical() == {"families": ["EVENT"]}


class TestAPoliticaNaIdentidade:
    """§84 — a política entra na impressão das features novas."""

    def test_trocar_a_janela_muda_a_impressao_do_espaco(self) -> None:
        outra = HistoricalContextPolicy(lookback_days=(7, 30))
        assert (
            match_state_raw_space_v2(context_policy=outra).fingerprint
            != match_state_raw_space_v2().fingerprint
        )

    def test_trocar_a_janela_muda_as_chaves_de_contagem(self) -> None:
        outra = HistoricalContextPolicy(lookback_days=(7, 30))
        chaves = match_state_raw_space_v2(context_policy=outra).keys
        assert "ctx_same_comp_matches_7d_home" in chaves
        assert "ctx_same_comp_matches_14d_home" not in chaves

    def test_a_politica_padrao_e_a_da_v2(self) -> None:
        catalogo = extended_feature_catalog()
        gap = catalogo.spec_of("ctx_same_comp_prev_gap_hours_home").definition
        assert gap.parameters["context_policy_fingerprint"] == DEFAULT_CONTEXT_POLICY.fingerprint

    def test_as_features_de_mercado_sao_intra_jogo(self) -> None:
        """§160 — o mercado MUDA com o corte, ao contrário do contexto."""
        catalogo = extended_feature_catalog()
        definicao = catalogo.spec_of("market_1x2_home_median").definition
        assert definicao.temporal_class is FeatureTemporalClass.INTRA_MATCH_CAUSAL

    def test_as_features_de_contexto_sao_pre_jogo(self) -> None:
        catalogo = extended_feature_catalog()
        definicao = catalogo.spec_of("ctx_same_comp_matches_14d_home").definition
        assert definicao.temporal_class is FeatureTemporalClass.PRE_MATCH
