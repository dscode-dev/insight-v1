"""Os contratos de feature — identidade, ordem, ausência e normalização.

O QUE ESTES TESTES PROTEGEM, e nenhum deles é «cobertura»:

    identidade semântica   mesma chave e versão com conteúdos diferentes é
                           erro, e não uma coincidência simpática
    a ordem é conteúdo     `[a, b]` e `[b, a]` são espaços diferentes
    a promessa estrutural  `live_comparable` com verdade retrospectiva não
                           constrói
    ausente ≠ zero         no valor, na máscara e na procedência
    normalização           escopo e corte de ajuste fazem parte da identidade
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.features.availability import (
    FactKind,
    FeatureAvailability,
    TemporalAvailability,
    TemporalAvailabilityPolicy,
)
from sports_intelligence.domain.features.definitions import (
    FeatureDefinition,
    FeatureOutputType,
    FeatureScope,
    FeatureTemporalClass,
)
from sports_intelligence.domain.features.leakage import LeakageReason
from sports_intelligence.domain.features.normalization import (
    DEFAULT_V1_NORMALIZER,
    FitCutoffKind,
    NormalizationMethod,
    NormalizationScope,
    NormalizerDefinition,
    NormalizerFitCutoff,
    NormalizerFitWindow,
)
from sports_intelligence.domain.features.provenance import (
    CONTRIBUTION_SAMPLE_LIMIT,
    FeatureContribution,
    FeatureProvenance,
    FeatureProvenanceClass,
    ProvenanceBuilder,
)
from sports_intelligence.domain.features.registry import FeatureDefinitionRegistry
from sports_intelligence.domain.features.snapshot import FeatureSnapshot
from sports_intelligence.domain.features.space import (
    CorpusRequirement,
    FeatureSpaceDefinition,
)
from sports_intelligence.domain.features.temporal import FeatureAsOf, TemporalMode
from sports_intelligence.domain.features.values import (
    ComputedFeature,
    FeatureAvailabilityMask,
)
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.temporal import Period, instant
from sports_intelligence.domain.shared.versioning import (
    FeatureSpaceVersion,
    NormalizerVersion,
    Version,
)
from tests.support.feature_fixtures import (
    KICKOFF,
    corte,
    definicao_de_teste,
    espaco_de_teste,
    origem,
    relogio_de_parede,
)


class TestAFeatureDefinition:
    """§31, §33, §34, §36, §37."""

    def test_a_identidade_carrega_chave_versao_e_impressao(self) -> None:
        definicao = definicao_de_teste()
        assert definicao.identity.startswith("test_event_count@v1.0#")
        assert len(definicao.fingerprint) == 64

    def test_a_mesma_declaracao_produz_a_mesma_impressao(self) -> None:
        assert definicao_de_teste().fingerprint == definicao_de_teste().fingerprint

    def test_parametro_diferente_muda_a_impressao(self) -> None:
        """§37. Mesma chave, mesma versão, janela de 5 contra 10 minutos: a
        declaração humana não distingue, e a impressão distingue."""
        cinco = definicao_de_teste(parameters={"window_minutes": 5})
        dez = definicao_de_teste(parameters={"window_minutes": 10})
        assert cinco.key == dez.key
        assert cinco.version == dez.version
        assert cinco.fingerprint != dez.fingerprint

    def test_a_descricao_nao_entra_na_impressao(self) -> None:
        """Reescrever um comentário não pode quebrar compatibilidade."""
        from dataclasses import replace

        original = definicao_de_teste()
        reescrita = replace(original, description="outra redação, mesmo cálculo")
        assert original.fingerprint == reescrita.fingerprint

    def test_chave_malformada_e_recusada(self) -> None:
        for ruim in ("Shots", "shots home", "s", "2shots", "shots-home"):
            with pytest.raises(ValidationError, match="chave de feature inválida"):
                definicao_de_teste(key=ruim)

    def test_feature_pre_jogo_nao_pode_depender_de_evento(self) -> None:
        """Ela seria recusada em todo cálculo — melhor recusar na declaração."""
        with pytest.raises(ValidationError, match="PRE_MATCH e declara depender"):
            FeatureDefinition(
                key="pre_match_shots",
                version=Version(major=1, minor=0),
                description="incoerente de propósito",
                output_type=FeatureOutputType.INTEGER,
                scope=FeatureScope.MATCH,
                temporal_class=FeatureTemporalClass.PRE_MATCH,
                required_fact_kinds=(FactKind.EVENT_ORIGINAL,),
            )

    def test_feature_que_depende_de_si_mesma_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="depende de si mesma"):
            definicao_de_teste(depends_on=("test_event_count",))


class TestOFeatureSpace:
    """§51 ao §57."""

    def test_a_ordem_e_parte_da_identidade(self) -> None:
        """§52, §55. Os mesmos números em eixos trocados não são o mesmo
        espaço — e a distância entre um vetor de um e outro do outro seria
        aritmética sobre dimensões diferentes."""
        a = definicao_de_teste(key="feature_a")
        b = definicao_de_teste(key="feature_b")
        primeiro = espaco_de_teste(a, b)
        invertido = espaco_de_teste(b, a)
        assert primeiro.keys == ("feature_a", "feature_b")
        assert invertido.keys == ("feature_b", "feature_a")
        assert primeiro.fingerprint != invertido.fingerprint

    def test_a_mesma_ordem_produz_a_mesma_impressao(self) -> None:
        a, b = definicao_de_teste(key="feature_a"), definicao_de_teste(key="feature_b")
        assert espaco_de_teste(a, b).fingerprint == espaco_de_teste(a, b).fingerprint

    def test_chave_repetida_e_recusada(self) -> None:
        """§56. Uma das duas seria ignorada, e ninguém saberia qual."""
        with pytest.raises(ValidationError, match="chave repetida"):
            espaco_de_teste(definicao_de_teste(), definicao_de_teste())

    def test_live_comparable_com_verdade_retrospectiva_nao_constroi(self) -> None:
        """§80. A combinação inválida não é recusada na revisão de código: ela
        não existe como objeto."""
        with pytest.raises(ValidationError, match="comparável com partida ao vivo"):
            espaco_de_teste(live_comparable=True, mode=TemporalMode.CANONICAL_FINAL)

    def test_espaco_retrospectivo_e_legitimo_quando_declarado(self) -> None:
        """A auditoria é um uso legítimo — o que não pode é ela se dizer
        comparável ao vivo."""
        espaco = espaco_de_teste(
            live_comparable=False, mode=TemporalMode.CANONICAL_FINAL
        )
        assert espaco.temporal_mode is TemporalMode.CANONICAL_FINAL

    def test_feature_pos_jogo_num_espaco_ao_vivo_e_recusada(self) -> None:
        pos_jogo = definicao_de_teste(
            key="final_score_diff",
            temporal_class=FeatureTemporalClass.POST_MATCH,
            families=(CoverageFamily.MATCH,),
        )
        with pytest.raises(ValidationError, match="pós-jogo"):
            espaco_de_teste(pos_jogo, live_comparable=True)

    def test_dependencia_ausente_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="depende de"):
            espaco_de_teste(definicao_de_teste(depends_on=("nao_existe",)))

    def test_ciclo_de_dependencia_e_recusado(self) -> None:
        """§105. E a mensagem traz o CAMINHO, não só «há um ciclo»."""
        a = definicao_de_teste(key="feature_a", depends_on=("feature_b",))
        b = definicao_de_teste(key="feature_b", depends_on=("feature_a",))
        with pytest.raises(ValidationError, match="cíclica"):
            espaco_de_teste(a, b)

    def test_exigencia_de_corpus_nao_declarada_e_recusada(self) -> None:
        """§57. A incompatibilidade precisa aparecer ANTES do cálculo."""
        com_odds = definicao_de_teste(key="odds_feature", families=(CoverageFamily.ODDS,))
        with pytest.raises(ValidationError, match="não declara a exigência"):
            FeatureSpaceDefinition(
                name="incoerente",
                version=FeatureSpaceVersion(major=1, minor=0),
                features=(com_odds,),
                requirement=CorpusRequirement.of(CoverageFamily.MATCH),
            )

    def test_corpus_sem_a_familia_exigida_e_recusado(self) -> None:
        espaco = espaco_de_teste()
        espaco.assert_compatible_with(frozenset({CoverageFamily.EVENT}))
        with pytest.raises(ValidationError, match="não publica"):
            espaco.assert_compatible_with(frozenset({CoverageFamily.MATCH}))

    def test_exigir_nao_e_garantir(self) -> None:
        """§58. «requires EVENT» é sobre a VERSÃO publicar a família, e não
        sobre toda partida ter eventos."""
        espaco = espaco_de_teste()
        assert espaco.requirement.families == (CoverageFamily.EVENT,)
        assert espaco.requirement.missing_from(frozenset({CoverageFamily.EVENT})) == ()


class TestORegistro:
    """§107, §108."""

    def test_mesma_chave_e_versao_com_conteudos_diferentes_e_recusado(self) -> None:
        """A pior das duplicatas: quem comparar dois números vai achar que
        comparou a mesma feature."""
        with pytest.raises(ValidationError, match="conteúdos diferentes"):
            FeatureDefinitionRegistry.of(
                (
                    definicao_de_teste(parameters={"window_minutes": 5}),
                    definicao_de_teste(parameters={"window_minutes": 10}),
                )
            )

    def test_registro_repetido_identico_tambem_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="registrada duas vezes"):
            FeatureDefinitionRegistry.of((definicao_de_teste(), definicao_de_teste()))

    def test_dependencia_desconhecida_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="não está no registro"):
            FeatureDefinitionRegistry.of((definicao_de_teste(depends_on=("fantasma",)),))

    def test_a_versao_mais_alta_e_a_atual(self) -> None:
        """E «mais alta» é por versão, não por ordem de registro."""
        registro = FeatureDefinitionRegistry.of(
            (
                definicao_de_teste(version=(2, 0)),
                definicao_de_teste(version=(1, 0)),
            )
        )
        assert str(registro.latest("test_event_count").version) == "v2.0"

    def test_a_iteracao_e_deterministica(self) -> None:
        definicoes = (
            definicao_de_teste(key="feature_b"),
            definicao_de_teste(key="feature_a"),
        )
        um = [d.key for d in FeatureDefinitionRegistry.of(definicoes)]
        outro = [d.key for d in FeatureDefinitionRegistry.of(tuple(reversed(definicoes)))]
        assert um == outro == ["feature_a", "feature_b"]


class TestOValorEAAusencia:
    """§41 ao §45. Ausente nunca é zero."""

    def test_zero_legitimo_e_ausencia_sao_distinguiveis(self) -> None:
        """§43. `red_cards_home = 0` é um fato; indisponível é outro."""
        definicao = definicao_de_teste(key="red_cards_home")
        zero = ComputedFeature.available(
            definition_key=definicao.key,
            definition_fingerprint=definicao.fingerprint,
            as_of=corte(),
            value=0,
            provenance=FeatureProvenance.of(FeatureProvenanceClass.DERIVED_FROM_CANONICAL),
        )
        ausente = ComputedFeature.unavailable(
            definition_key=definicao.key,
            definition_fingerprint=definicao.fingerprint,
            as_of=corte(),
            availability=FeatureAvailability.SOURCE_UNAVAILABLE,
        )
        assert zero.is_available
        assert zero.numeric == 0
        assert not ausente.is_available
        assert ausente.numeric is None
        assert zero.as_canonical() != ausente.as_canonical()

    def test_disponivel_sem_valor_nao_constroi(self) -> None:
        with pytest.raises(ValidationError, match="AVAILABLE sem valor"):
            ComputedFeature(
                definition_key="x_feature",
                definition_fingerprint="a" * 64,
                as_of=corte(),
                availability=FeatureAvailability.AVAILABLE,
            )

    def test_indisponivel_com_valor_nao_constroi(self) -> None:
        from sports_intelligence.domain.shared.feature_value import FeatureValue

        with pytest.raises(ValidationError, match="indisponível carregando valor"):
            ComputedFeature(
                definition_key="x_feature",
                definition_fingerprint="a" * 64,
                as_of=corte(),
                availability=FeatureAvailability.SOURCE_UNAVAILABLE,
                value=FeatureValue.of(3),
            )

    def test_recusa_temporal_exige_motivo(self) -> None:
        """§46. «Indisponível» sem motivo não conserta nada."""
        with pytest.raises(ValidationError, match="sem dizer qual"):
            ComputedFeature(
                definition_key="x_feature",
                definition_fingerprint="a" * 64,
                as_of=corte(),
                availability=FeatureAvailability.TEMPORALLY_UNAVAILABLE,
            )

    def test_a_mascara_preserva_o_motivo_de_cada_ausencia(self) -> None:
        """§45. Um booleano faria três investigações virarem uma."""
        definicao = definicao_de_teste()
        mascara = FeatureAvailabilityMask.of(
            (
                ComputedFeature.available(
                    definition_key="a_feature",
                    definition_fingerprint=definicao.fingerprint,
                    as_of=corte(),
                    value=1,
                    provenance=FeatureProvenance.none(),
                ),
                ComputedFeature.unavailable(
                    definition_key="b_feature",
                    definition_fingerprint=definicao.fingerprint,
                    as_of=corte(),
                    availability=FeatureAvailability.TEMPORALLY_UNAVAILABLE,
                    leakage_reason=LeakageReason.EFFECTIVE_TIME_AFTER_CUTOFF,
                ),
                ComputedFeature.unavailable(
                    definition_key="c_feature",
                    definition_fingerprint=definicao.fingerprint,
                    as_of=corte(),
                    availability=FeatureAvailability.INSUFFICIENT_COVERAGE,
                ),
            )
        )
        assert mascara.available_count == 1
        assert not mascara.is_complete
        assert mascara.state_of("b_feature") is FeatureAvailability.TEMPORALLY_UNAVAILABLE
        assert mascara.state_of("c_feature") is FeatureAvailability.INSUFFICIENT_COVERAGE


class TestAProcedencia:
    """§47 ao §50."""

    def test_o_digest_nao_depende_da_ordem_de_leitura(self) -> None:
        """§50. Duas execuções que leram os mesmos fatos em ordens diferentes
        precisam produzir a mesma procedência."""
        contribuicoes = [
            FeatureContribution(kind="EVENT", reference=f"ev-{n}") for n in range(5)
        ]
        direta = FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL, contribuicoes
        )
        invertida = FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL, reversed(contribuicoes)
        )
        assert direta.contribution_digest == invertida.contribution_digest

    def test_conjuntos_diferentes_produzem_digests_diferentes(self) -> None:
        um = FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL,
            [FeatureContribution(kind="EVENT", reference="ev-1")],
        )
        outro = FeatureProvenance.of(
            FeatureProvenanceClass.DERIVED_FROM_CANONICAL,
            [FeatureContribution(kind="EVENT", reference="ev-2")],
        )
        assert um.contribution_digest != outro.contribution_digest

    def test_a_amostra_e_limitada_e_a_contagem_e_exata(self) -> None:
        """§49. Apresentar a amostra como o conjunto seria a mentira mais fácil
        de cometer aqui."""
        construtor = ProvenanceBuilder()
        for n in range(100):
            construtor.add("EVENT", f"ev-{n}")
        procedencia = construtor.finish(FeatureProvenanceClass.DERIVED_FROM_CANONICAL)
        assert procedencia.count == 100
        assert len(procedencia.sample) == CONTRIBUTION_SAMPLE_LIMIT
        assert procedencia.sample_truncated

    def test_procedencia_de_valor_nao_calculado_e_vazia(self) -> None:
        vazia = FeatureProvenance.none()
        assert vazia.count == 0
        assert vazia.contribution_digest == ""


class TestAPoliticaTemporal:
    """§12, §134."""

    def test_a_politica_classifica_todas_as_familias(self) -> None:
        politica = TemporalAvailabilityPolicy.default()
        for familia in FactKind:
            assert politica.availability_of(familia) in TemporalAvailability

    def test_politica_incompleta_e_recusada(self) -> None:
        """Uma família esquecida cairia num default silencioso."""
        with pytest.raises(ValidationError, match="sem classificação"):
            TemporalAvailabilityPolicy(
                version=Version(major=1, minor=0),
                classification={FactKind.MATCH_RESULT: TemporalAvailability.POST_MATCH_ONLY},
            )

    def test_conteudo_diferente_muda_a_impressao(self) -> None:
        """§134. Mesma versão, classificação diferente: causalidades
        diferentes, e a impressão é o que impede compará-las."""
        padrao = TemporalAvailabilityPolicy.default()
        estrita = TemporalAvailabilityPolicy.strict_observed()
        assert padrao.version == estrita.version
        assert padrao.fingerprint != estrita.fingerprint

    def test_a_descricao_nao_entra_na_impressao(self) -> None:
        from dataclasses import replace

        padrao = TemporalAvailabilityPolicy.default()
        outra = replace(padrao, description="outra redação")
        assert padrao.fingerprint == outra.fingerprint


class TestONormalizador:
    """§83 ao §90."""

    def test_a_identidade_carrega_metodo_escopo_e_corte(self) -> None:
        assert DEFAULT_V1_NORMALIZER.identity.startswith("competition_median_iqr@v1.0#")

    def test_corte_diferente_muda_a_impressao(self) -> None:
        """§89. Dois normalizadores iguais em tudo menos no corte produzem
        escalas diferentes — e a impressão precisa dizer isso."""
        from dataclasses import replace

        causal = DEFAULT_V1_NORMALIZER
        retrospectivo = replace(
            causal, fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.FULL_POPULATION)
        )
        assert causal.fingerprint != retrospectivo.fingerprint

    def test_escopo_global_e_recusado_para_espaco_ao_vivo(self) -> None:
        """§85, §86. A V1 normaliza por competição."""
        global_ = NormalizerDefinition(
            key="global_z",
            version=NormalizerVersion(major=1, minor=0),
            method=NormalizationMethod.Z_SCORE,
            scope=NormalizationScope.GLOBAL,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
        )
        assert not global_.is_causal
        with pytest.raises(ValidationError, match="escopo GLOBAL"):
            global_.assert_usable_for_live_comparable()

    def test_ajuste_retrospectivo_e_recusado_para_espaco_ao_vivo(self) -> None:
        """§87. A escala carregaria dados posteriores ao jogo avaliado."""
        from dataclasses import replace

        retrospectivo = replace(
            DEFAULT_V1_NORMALIZER,
            fit_cutoff=NormalizerFitCutoff(kind=FitCutoffKind.FULL_POPULATION),
        )
        with pytest.raises(ValidationError, match="população inteira"):
            retrospectivo.assert_usable_for_live_comparable()

    def test_o_normalizador_padrao_da_v1_e_causal(self) -> None:
        assert DEFAULT_V1_NORMALIZER.is_causal
        DEFAULT_V1_NORMALIZER.assert_usable_for_live_comparable()

    def test_a_janela_recusa_dado_posterior_ao_jogo_avaliado(self) -> None:
        """§88. Ajustar com dado de maio para avaliar março."""
        janela = NormalizerFitWindow(
            cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH),
            evaluated_match_start=KICKOFF,
        )
        assert janela.admits(relogio_de_parede(-60))
        assert not janela.admits(relogio_de_parede(60))

    def test_a_janela_sem_referencia_recusa_tudo(self) -> None:
        """Fail-closed: sem saber quando a partida avaliada começou, não há
        como afirmar que o dado é anterior a ela."""
        janela = NormalizerFitWindow(
            cutoff=NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_EVALUATED_MATCH)
        )
        assert not janela.admits(KICKOFF)

    def test_corte_por_instante_exige_o_instante(self) -> None:
        with pytest.raises(ValidationError, match="antes de quando"):
            NormalizerFitCutoff(kind=FitCutoffKind.BEFORE_INSTANT)

    def test_corte_que_nao_usa_instante_recusa_um(self) -> None:
        with pytest.raises(ValidationError, match="não seria usado"):
            NormalizerFitCutoff(
                kind=FitCutoffKind.FULL_POPULATION, instant=instant(KICKOFF)
            )


class TestOSnapshot:
    """§61 ao §65, §140 ao §145."""

    def _computada(
        self,
        definicao: FeatureDefinition,
        as_of: FeatureAsOf | None = None,
        valor: int = 1,
    ) -> ComputedFeature:
        return ComputedFeature.available(
            definition_key=definicao.key,
            definition_fingerprint=definicao.fingerprint,
            as_of=as_of or corte(),
            value=valor,
            provenance=FeatureProvenance.none(),
        )

    def test_a_impressao_e_deterministica(self) -> None:
        """§139, §163. Mesmo corpus, espaço, corte e política ⇒ mesma
        identidade."""
        definicao = definicao_de_teste()
        espaco = espaco_de_teste(definicao)
        politica = TemporalAvailabilityPolicy.default()
        primeiro = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(),
            policy=politica,
            features=(self._computada(definicao),),
        )
        segundo = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(),
            policy=politica,
            features=(self._computada(definicao),),
        )
        assert primeiro.fingerprint == segundo.fingerprint

    def test_corpus_diferente_muda_a_impressao(self) -> None:
        """§142."""
        definicao = definicao_de_teste()
        espaco = espaco_de_teste(definicao)
        politica = TemporalAvailabilityPolicy.default()
        base = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(),
            policy=politica,
            features=(self._computada(definicao),),
        )
        outro = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(fingerprint="b" * 64),
            policy=politica,
            features=(self._computada(definicao),),
        )
        assert base.fingerprint != outro.fingerprint

    def test_politica_diferente_muda_a_impressao(self) -> None:
        """§144. Mudança de causalidade muda a identidade do estado."""
        definicao = definicao_de_teste()
        espaco = espaco_de_teste(definicao)
        base = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(),
            policy=TemporalAvailabilityPolicy.default(),
            features=(self._computada(definicao),),
        )
        estrita = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco,
            source=origem(),
            policy=TemporalAvailabilityPolicy.strict_observed(),
            features=(self._computada(definicao),),
        )
        assert base.fingerprint != estrita.fingerprint

    def test_corte_diferente_muda_a_impressao(self) -> None:
        """§145. Snapshot de 62' ≠ snapshot de 63'."""
        definicao = definicao_de_teste()
        espaco = espaco_de_teste(definicao)
        politica = TemporalAvailabilityPolicy.default()
        aos_62 = corte(62)
        aos_63 = corte(63)
        um = FeatureSnapshot.of(
            as_of=aos_62,
            space=espaco,
            source=origem(),
            policy=politica,
            features=(self._computada(definicao, as_of=aos_62),),
        )
        outro = FeatureSnapshot.of(
            as_of=aos_63,
            space=espaco,
            source=origem(),
            policy=politica,
            features=(self._computada(definicao, as_of=aos_63),),
        )
        assert um.fingerprint != outro.fingerprint

    def test_ordem_fora_do_espaco_e_recusada(self) -> None:
        """Fora da ordem, os eixos trocam de lugar."""
        a = definicao_de_teste(key="feature_a")
        b = definicao_de_teste(key="feature_b")
        espaco = espaco_de_teste(a, b)
        with pytest.raises(ValidationError, match="A ordem é parte da identidade"):
            FeatureSnapshot.of(
                as_of=corte(),
                space=espaco,
                source=origem(),
                policy=TemporalAvailabilityPolicy.default(),
                features=(self._computada(b), self._computada(a)),
            )

    def test_feature_de_outra_impressao_e_recusada(self) -> None:
        """§33. Mesmo nome, definições diferentes."""
        declarada = definicao_de_teste(parameters={"window_minutes": 5})
        outra = definicao_de_teste(parameters={"window_minutes": 10})
        espaco = espaco_de_teste(declarada)
        with pytest.raises(ValidationError, match="definições diferentes"):
            FeatureSnapshot.of(
                as_of=corte(),
                space=espaco,
                source=origem(),
                policy=TemporalAvailabilityPolicy.default(),
                features=(self._computada(outra),),
            )

    def test_a_mascara_e_derivada_e_nao_guardada(self) -> None:
        definicao = definicao_de_teste()
        snapshot = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco_de_teste(definicao),
            source=origem(),
            policy=TemporalAvailabilityPolicy.default(),
            features=(
                ComputedFeature.unavailable(
                    definition_key=definicao.key,
                    definition_fingerprint=definicao.fingerprint,
                    as_of=corte(),
                    availability=FeatureAvailability.INSUFFICIENT_COVERAGE,
                ),
            ),
        )
        assert not snapshot.is_complete
        assert snapshot.mask.available_count == 0

    def test_nada_incidental_entra_na_impressao(self) -> None:
        """§141. Nem id de execução, nem carimbo, nem id de linha."""
        definicao = definicao_de_teste()
        snapshot = FeatureSnapshot.of(
            as_of=corte(),
            space=espaco_de_teste(definicao),
            source=origem(),
            policy=TemporalAvailabilityPolicy.default(),
            features=(self._computada(definicao),),
        )
        forma = snapshot.as_canonical()
        texto = str(forma)
        for proibido in ("created_at", "run_id", "process", "row_id", "version_id"):
            assert proibido not in texto


class TestOPeriodoOrdenado:
    """§8, §10. A fase ordena, e a ordem é a do jogo."""

    def test_a_ordem_das_fases_e_a_do_jogo(self) -> None:
        assert Period.PRE_MATCH.order < Period.FIRST_HALF.order
        assert Period.FIRST_HALF.order < Period.HALF_TIME.order < Period.SECOND_HALF.order
        assert Period.SECOND_HALF.order < Period.EXTRA_TIME_FIRST.order
        assert Period.PENALTY_SHOOTOUT.order < Period.FULL_TIME.order

    def test_a_ordem_alfabetica_nao_serve(self) -> None:
        """`EXTRA_TIME_FIRST` viria antes de `FIRST_HALF` — a prorrogação
        antes do primeiro tempo."""
        alfabetica = sorted(Period, key=lambda p: p.value)
        do_jogo = sorted(Period, key=lambda p: p.order)
        assert alfabetica != do_jogo
