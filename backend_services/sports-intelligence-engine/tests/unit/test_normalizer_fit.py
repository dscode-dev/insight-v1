"""O ajuste e a aplicação do normalizador — exatos, escopados e sem epsilon.

O QUE ESTES TESTES PROVAM. A parte fácil é a conta: mediana, quartis e
`(x - mediana) / IQR`. A parte que importa é o que o ajustador RECUSA:

    escopo global           uma escala comum entre ligas apaga a diferença
    competição errada       o artefato da Premier não normaliza La Liga
    feature errada          o de `shots_home_5m` não normaliza `xg_home_5m`
    amostra insuficiente    mediana de amostra declarada inadequada
    IQR zero                dividir por zero, ou pior, somar um epsilon

O ÚLTIMO É O MAIS TENTADOR. `max(iqr, 1e-6)` faz o código parar de quebrar e
inventa uma escala: uma distribuição sem dispersão passa a produzir valores
normalizados enormes, e eles parecem sinal.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from sports_intelligence.domain.features.availability import FeatureAvailability
from sports_intelligence.domain.features.extraction.catalog import (
    production_feature_catalog,
)
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.fitting.fitter import (
    DEFAULT_MINIMUM_AVAILABLE_SAMPLES,
    MINIMUM_SAMPLES_PARAMETER,
    RobustNormalizerFitter,
)
from sports_intelligence.domain.features.fitting.population import (
    FeaturePopulation,
)
from sports_intelligence.domain.features.fitting.transformer import (
    ROBUST_SCALING_METHOD,
    RobustNormalizerTransformer,
)
from sports_intelligence.domain.features.normalization import (
    DEFAULT_V1_NORMALIZER,
    FitCutoffKind,
    NormalizationMethod,
    NormalizationScope,
    NormalizerDefinition,
    NormalizerFitCutoff,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.versioning import NormalizerVersion
from tests.support.v2_fixtures import COMPETICAO, observacao, populacao, valores_de_zero_a

CORPUS = "a" * 64
ESPACO = "b" * 64


def feature() -> object:
    return production_feature_catalog().spec_of("shots_home_5m").definition


def ajustar(
    valores: list[str | None],
    *,
    definicao: NormalizerDefinition | None = None,
    feature_key: str = "shots_home_5m",
) -> NormalizerFitArtifact:
    fitter = RobustNormalizerFitter(definition=definicao or DEFAULT_V1_NORMALIZER)
    return fitter.fit(
        populacao(valores, feature_key=feature_key),
        feature=production_feature_catalog().spec_of(feature_key).definition,
        source_corpus_fingerprint=CORPUS,
        source_space_fingerprint=ESPACO,
    )


class TestAPopulacao:
    """§104 ao §107, §119, §120."""

    def test_ela_ordena_e_o_digest_independe_da_ordem(self) -> None:
        """§106."""
        direta = FeaturePopulation.of(
            COMPETICAO, "shots_home_5m", [observacao(n, str(n)) for n in range(5)]
        )
        invertida = FeaturePopulation.of(
            COMPETICAO,
            "shots_home_5m",
            [observacao(n, str(n)) for n in reversed(range(5))],
        )
        assert direta.digest == invertida.digest
        assert direta.observations == invertida.observations

    def test_um_membro_a_mais_muda_o_digest(self) -> None:
        cinco = populacao(valores_de_zero_a(5))
        seis = populacao(valores_de_zero_a(6))
        assert cinco.digest != seis.digest

    def test_um_valor_diferente_muda_o_digest(self) -> None:
        original = populacao(["1", "2", "3"])
        alterada = populacao(["1", "2", "4"])
        assert original.digest != alterada.digest

    def test_observacao_repetida_e_recusada(self) -> None:
        """§107 — ela deslocaria a mediana sem que nada denunciasse."""
        with pytest.raises(ValidationError, match="repetida"):
            FeaturePopulation.of(
                COMPETICAO,
                "shots_home_5m",
                [observacao(1, "1"), observacao(1, "2")],
            )

    def test_indisponiveis_contam_no_total_e_nao_na_distribuicao(self) -> None:
        """§119, §120."""
        pop = populacao(["1", None, "3", None, "5"])
        assert pop.size == 5
        assert pop.available_size == 3
        # A ORDEM DOS VALORES É A CANÔNICA DA POPULAÇÃO, e não a de inserção:
        # ela é derivada da identidade da observação, para que o digest não
        # dependa de quem leu primeiro. Os quantis ordenam de novo, então o que
        # importa aqui é o CONJUNTO.
        assert sorted(pop.values()) == [Decimal(1), Decimal(3), Decimal(5)]

    def test_o_digest_de_populacao_vazia_e_vazio(self) -> None:
        assert FeaturePopulation.of(COMPETICAO, "shots_home_5m", []).digest == ""

    def test_corpus_diferente_muda_o_digest(self) -> None:
        """§105 — o mesmo jogo pode ter outro valor noutro corpus."""
        a = FeaturePopulation.of(
            COMPETICAO, "shots_home_5m", [observacao(1, "1", corpus="a" * 64)]
        )
        b = FeaturePopulation.of(
            COMPETICAO, "shots_home_5m", [observacao(1, "1", corpus="c" * 64)]
        )
        assert a.digest != b.digest


class TestOAjuste:
    """§98, §99, §115, §121 ao §127."""

    def test_o_ajuste_produz_mediana_e_quartis_exatos(self) -> None:
        """0..29: n=30. Mediana 14,5; Q1 7,25; Q3 21,75; IQR 14,5."""
        artefato = ajustar(valores_de_zero_a(30))
        assert artefato.status is FitStatus.FITTED
        assert artefato.median == Decimal("14.5")
        assert artefato.q1 == Decimal("7.25")
        assert artefato.q3 == Decimal("21.75")
        assert artefato.iqr == Decimal("14.5")

    def test_o_artefato_registra_os_dois_totais(self) -> None:
        """§120 — total e disponíveis, para auditoria."""
        artefato = ajustar([*valores_de_zero_a(30), None, None])
        assert artefato.population_count == 32
        assert artefato.available_count == 30

    def test_amostra_insuficiente_nao_publica_mediana(self) -> None:
        """§121, §123."""
        artefato = ajustar(valores_de_zero_a(29))
        assert artefato.status is FitStatus.INSUFFICIENT_SAMPLE
        assert artefato.median is None
        assert not artefato.is_usable

    def test_o_minimo_vem_da_declaracao(self) -> None:
        """§122 — o limiar é política versionada, e não constante do código."""
        permissivo = NormalizerDefinition(
            key="competition_median_iqr",
            version=NormalizerVersion(major=1, minor=1),
            method=NormalizationMethod.MEDIAN_IQR,
            scope=NormalizationScope.COMPETITION,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
            parameters={MINIMUM_SAMPLES_PARAMETER: 5},
        )
        artefato = ajustar(valores_de_zero_a(5), definicao=permissivo)
        assert artefato.status is FitStatus.FITTED

    def test_o_minimo_padrao_e_o_declarado(self) -> None:
        assert (
            RobustNormalizerFitter(
                definition=DEFAULT_V1_NORMALIZER
            ).minimum_available_samples
            == DEFAULT_MINIMUM_AVAILABLE_SAMPLES
            == 30
        )

    def test_dispersao_nula_e_um_estado_e_nao_um_erro(self) -> None:
        """§124, §126 — a mediana existe; a escala não."""
        artefato = ajustar(["7"] * 30)
        assert artefato.status is FitStatus.DEGENERATE_SCALE
        assert artefato.median == Decimal(7)
        assert artefato.iqr == Decimal(0)
        assert not artefato.is_usable

    def test_o_escopo_global_e_recusado_na_construcao(self) -> None:
        """§109, §110."""
        global_ = NormalizerDefinition(
            key="global",
            version=NormalizerVersion(major=1, minor=0),
            method=NormalizationMethod.MEDIAN_IQR,
            scope=NormalizationScope.GLOBAL,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
        )
        with pytest.raises(ValidationError, match="GLOBAL"):
            RobustNormalizerFitter(definition=global_)

    def test_metodo_incompativel_e_recusado(self) -> None:
        z = NormalizerDefinition(
            key="z",
            version=NormalizerVersion(major=1, minor=0),
            method=NormalizationMethod.Z_SCORE,
            scope=NormalizationScope.COMPETITION,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
        )
        with pytest.raises(ValidationError, match="calcula mediana e"):
            RobustNormalizerFitter(definition=z)

    def test_populacao_de_outra_feature_e_recusada(self) -> None:
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        with pytest.raises(ValidationError, match="população de"):
            fitter.fit(
                populacao(valores_de_zero_a(30), feature_key="xg_home_5m"),
                feature=production_feature_catalog()
                .spec_of("shots_home_5m")
                .definition,
                source_corpus_fingerprint=CORPUS,
                source_space_fingerprint=ESPACO,
            )

    def test_o_corte_retrospectivo_e_recusado_para_espaco_ao_vivo(self) -> None:
        """§114."""
        retrospectivo = NormalizerDefinition(
            key="retro",
            version=NormalizerVersion(major=1, minor=0),
            method=NormalizationMethod.MEDIAN_IQR,
            scope=NormalizationScope.COMPETITION,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.FULL_POPULATION),
        )
        fitter = RobustNormalizerFitter(definition=retrospectivo)
        with pytest.raises(ValidationError, match="população inteira"):
            fitter.assert_causal_for_live_comparable()


class TestAImpressaoDoArtefato:
    """§140 ao §147 — a identidade depende de tudo que a produziu."""

    def test_a_mesma_populacao_da_a_mesma_impressao(self) -> None:
        """§142."""
        assert (
            ajustar(valores_de_zero_a(30)).fingerprint
            == ajustar(valores_de_zero_a(30)).fingerprint
        )

    def test_um_valor_diferente_muda_a_impressao(self) -> None:
        """§143."""
        base = valores_de_zero_a(30)
        alterada = [*base[:-1], "999"]
        assert ajustar(base).fingerprint != ajustar(alterada).fingerprint

    def test_um_membro_a_mais_muda_a_impressao(self) -> None:
        """§144."""
        assert (
            ajustar(valores_de_zero_a(30)).fingerprint
            != ajustar(valores_de_zero_a(31)).fingerprint
        )

    def test_competicao_diferente_muda_a_impressao(self) -> None:
        """§145."""
        outra = CompetitionId.derive("pr054", "outra-liga")
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        artefato = fitter.fit(
            FeaturePopulation.of(
                outra,
                "shots_home_5m",
                [observacao(n, str(n)) for n in range(30)],
            ),
            feature=production_feature_catalog().spec_of("shots_home_5m").definition,
            source_corpus_fingerprint=CORPUS,
            source_space_fingerprint=ESPACO,
        )
        assert artefato.fingerprint != ajustar(valores_de_zero_a(30)).fingerprint

    def test_corte_diferente_muda_a_impressao(self) -> None:
        """§146."""
        from datetime import UTC, datetime

        from sports_intelligence.domain.shared.temporal import instant

        outro = NormalizerDefinition(
            key="competition_median_iqr",
            version=NormalizerVersion(major=1, minor=0),
            method=NormalizationMethod.MEDIAN_IQR,
            scope=NormalizationScope.COMPETITION,
            fit_cutoff=NormalizerFitCutoff(
                kind=FitCutoffKind.BEFORE_INSTANT,
                instant=instant(datetime(2026, 1, 1, tzinfo=UTC)),
            ),
        )
        assert (
            ajustar(valores_de_zero_a(30), definicao=outro).fingerprint
            != ajustar(valores_de_zero_a(30)).fingerprint
        )

    def test_corpus_diferente_muda_a_impressao(self) -> None:
        """§147."""
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        outro = fitter.fit(
            populacao(valores_de_zero_a(30)),
            feature=production_feature_catalog().spec_of("shots_home_5m").definition,
            source_corpus_fingerprint="f" * 64,
            source_space_fingerprint=ESPACO,
        )
        assert outro.fingerprint != ajustar(valores_de_zero_a(30)).fingerprint

    def test_a_ordem_da_populacao_nao_muda_a_impressao(self) -> None:
        """§106, §217."""
        fitter = RobustNormalizerFitter(definition=DEFAULT_V1_NORMALIZER)
        definicao = production_feature_catalog().spec_of("shots_home_5m").definition
        invertida = fitter.fit(
            FeaturePopulation.of(
                COMPETICAO,
                "shots_home_5m",
                [observacao(n, str(n)) for n in reversed(range(30))],
            ),
            feature=definicao,
            source_corpus_fingerprint=CORPUS,
            source_space_fingerprint=ESPACO,
        )
        assert invertida.fingerprint == ajustar(valores_de_zero_a(30)).fingerprint


class TestATransformacao:
    """§129 ao §139, §148, §149."""

    def _transformador(
        self, valores: list[str | None] | None = None
    ) -> RobustNormalizerTransformer:
        return RobustNormalizerTransformer(
            artifact=ajustar(valores or valores_de_zero_a(30))
        )

    def test_o_valor_na_mediana_vira_zero(self) -> None:
        """§148."""
        artefato = ajustar(valores_de_zero_a(30))
        assert artefato.median is not None
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=artefato.median,
        )
        assert resultado.scaled == Decimal(0)

    def test_o_valor_no_q3_da_a_razao_exata(self) -> None:
        """§149 — `(q3 - mediana) / IQR`, sem arredondamento implícito."""
        artefato = ajustar(valores_de_zero_a(30))
        assert artefato.q3 is not None
        assert artefato.median is not None
        assert artefato.iqr is not None
        esperado = (artefato.q3 - artefato.median) / artefato.iqr
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=artefato.q3,
        )
        assert resultado.scaled == esperado.quantize(Decimal("0.000000000001")).normalize()

    def test_o_valor_cru_sobrevive_a_transformacao(self) -> None:
        """§94, §218 — nada é mutado; os dois viajam juntos."""
        artefato = ajustar(valores_de_zero_a(30))
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal("3"),
        )
        assert resultado.raw == Decimal(3)
        assert resultado.scaled is not None
        assert resultado.artifact_fingerprint == artefato.fingerprint

    def test_o_metodo_nao_se_chama_z_score(self) -> None:
        """§100 — `z` carrega expectativas que esta escala não sustenta."""
        artefato = ajustar(valores_de_zero_a(30))
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal("3"),
        )
        assert resultado.method == ROBUST_SCALING_METHOD == "MEDIAN_IQR_ROBUST_SCALE_V1"
        assert "z_score" not in resultado.method.lower()

    def test_zero_cru_e_normalizavel(self) -> None:
        """§134."""
        artefato = ajustar(valores_de_zero_a(30))
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal(0),
        )
        assert resultado.is_available
        assert resultado.scaled is not None
        assert resultado.scaled < 0

    def test_valor_cru_ausente_produz_normalizado_ausente(self) -> None:
        """§133."""
        artefato = ajustar(valores_de_zero_a(30))
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=None,
        )
        assert not resultado.is_available
        assert resultado.raw is None
        assert resultado.availability is FeatureAvailability.SOURCE_UNAVAILABLE

    def test_a_feature_errada_e_recusada(self) -> None:
        """§131."""
        with pytest.raises(ValidationError, match="features diferentes"):
            self._transformador().transform(
                feature_key="xg_home_5m",
                feature_fingerprint="0" * 64,
                competition_id=COMPETICAO,
                raw=Decimal(1),
            )

    def test_a_competicao_errada_e_recusada(self) -> None:
        """§132 — fail-closed: o valor resultante pareceria plausível."""
        artefato = ajustar(valores_de_zero_a(30))
        with pytest.raises(ValidationError, match="competição"):
            self._transformador().transform(
                feature_key="shots_home_5m",
                feature_fingerprint=artefato.feature_fingerprint,
                competition_id=CompetitionId.derive("pr054", "outra-liga"),
                raw=Decimal(1),
            )

    def test_dispersao_nula_nao_normaliza_e_nao_inventa_epsilon(self) -> None:
        """§124, §125, §127 — o cru continua válido (§128)."""
        artefato = ajustar(["7"] * 30)
        resultado = RobustNormalizerTransformer(artifact=artefato).transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal("9"),
        )
        assert not resultado.is_available
        assert resultado.scaled is None
        assert resultado.raw == Decimal(9)
        assert resultado.availability is FeatureAvailability.NOT_APPLICABLE

    def test_amostra_insuficiente_nao_normaliza(self) -> None:
        artefato = ajustar(valores_de_zero_a(10))
        resultado = RobustNormalizerTransformer(artifact=artefato).transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal("3"),
        )
        assert not resultado.is_available
        assert resultado.availability is FeatureAvailability.INSUFFICIENT_COVERAGE

    def test_valores_extremos_nao_sao_clipados(self) -> None:
        """§136, §137 — se a conta dá -12,4, o valor é -12,4."""
        artefato = ajustar(valores_de_zero_a(30))
        resultado = self._transformador().transform(
            feature_key="shots_home_5m",
            feature_fingerprint=artefato.feature_fingerprint,
            competition_id=COMPETICAO,
            raw=Decimal("-1000"),
        )
        assert resultado.scaled is not None
        assert resultado.scaled < Decimal(-60)

    def test_a_transformacao_de_um_computed_converte_pelo_texto(self) -> None:
        """§135 — `float` direto para `Decimal` traria a representação binária."""
        from tests.support.snapshot_fixtures import extrair

        computada = extrair().value_of("shots_home_5m")
        resultado = self._transformador().transform_computed(
            computada, competition_id=COMPETICAO
        )
        assert resultado.raw == Decimal("3")
        assert resultado.is_available


class TestOArtefato:
    """As recusas do próprio contrato."""

    def test_disponiveis_acima_do_total_e_recusado(self) -> None:
        artefato = ajustar(valores_de_zero_a(30))
        from dataclasses import replace

        with pytest.raises(ValidationError, match="subconjunto é maior"):
            replace(artefato, available_count=99)

    def test_fitted_sem_parametros_e_recusado(self) -> None:
        artefato = ajustar(valores_de_zero_a(30))
        from dataclasses import replace

        with pytest.raises(ValidationError, match="FITTED sem"):
            replace(artefato, median=None)

    def test_fitted_com_iqr_zero_e_recusado(self) -> None:
        artefato = ajustar(valores_de_zero_a(30))
        from dataclasses import replace

        with pytest.raises(ValidationError, match="DEGENERATE_SCALE"):
            replace(artefato, iqr=Decimal(0))

    def test_a_identidade_e_legivel(self) -> None:
        artefato = ajustar(valores_de_zero_a(30))
        assert "shots_home_5m" in artefato.identity
        assert artefato.fingerprint[:16] in artefato.identity
