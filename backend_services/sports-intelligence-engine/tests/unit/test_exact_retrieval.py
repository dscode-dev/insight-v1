"""Os contratos da recuperação — e os goldens calculados à mão.

O QUE FAZ DE UM GOLDEN UM GOLDEN. `q=[0,0]`, `c=[3,4]`, `d²=25`. Se este teste
falhar, o número esperado não precisa ser recalculado por ninguém: ele é o
teorema de Pitágoras, e a única coisa que pode ter mudado é o código.

    É POR ISSO QUE O PERFIL SINTÉTICO TEM DOIS EIXOS. Com catorze, o valor
    esperado sairia de uma execução anterior — e um golden que se calcula
    rodando o código que ele testa não prova nada.

O QUE ESTE ARQUIVO NÃO TESTA: a invariância sob ordem, lote e `K`. Isso é de
propriedade, e está em `tests/property/test_exact_retrieval_invariants.py`.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime

import pytest

from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    TransformStrategy,
    plan_for,
)
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    CandidateSampling,
    CandidateUniversePolicy,
    CompetitionScope,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.distance import (
    DistanceMethod,
    distance_text,
)
from sports_intelligence.domain.retrieval.profile import (
    DEFAULT_RETRIEVAL_PROFILE,
    AxisSelection,
    MissingPolicy,
    WeightPolicy,
)
from sports_intelligence.domain.retrieval.query import MAX_K, HistoricalRetrievalQuery
from sports_intelligence.domain.retrieval.timepoint import (
    GRID_STOPPAGE,
    GridTimePoint,
    TimeAlignmentPolicy,
)
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import CompetitionId
from sports_intelligence.domain.shared.temporal import Period, instant
from tests.support.retrieval_fixtures import (
    EIXO_A,
    LIGA_A,
    distancia,
    pedido,
    perfil,
)


class TestOsGoldensDaDistancia:
    """§106, §108 — calculados à mão, e não por uma execução anterior."""

    def test_o_triangulo_3_4_5(self) -> None:
        """`q=[0,0]`, `c=[3,4]` → `d² = 9 + 16 = 25`."""
        assert distancia().evaluate((0.0, 0.0), (3.0, 4.0)) == 25.0

    def test_o_candidato_mais_proximo(self) -> None:
        """`b=[1,1]` → `d² = 2`, e `2 < 25`, logo `b` vem antes de `a`."""
        d = distancia()
        assert d.evaluate((0.0, 0.0), (1.0, 1.0)) == 2.0
        assert d.evaluate((0.0, 0.0), (1.0, 1.0)) < d.evaluate((0.0, 0.0), (3.0, 4.0))

    def test_valores_negativos(self) -> None:
        """`q=[-1,-1]`, `c=[1,1]` → `(-2)² + (-2)² = 8`."""
        assert distancia().evaluate((-1.0, -1.0), (1.0, 1.0)) == 8.0

    def test_a_ordem_dos_eixos_nao_muda_a_soma(self) -> None:
        """`fsum` é exata, então trocar os pares não muda o último bit."""
        d = distancia()
        assert d.evaluate((0.1, 0.2), (0.3, 0.4)) == d.evaluate((0.2, 0.1), (0.4, 0.3))

    def test_fsum_e_sum_CONCORDAM_nas_magnitudes_deste_dataset(self) -> None:
        """O que de fato acontece — e o que a documentação NÃO deve alegar.

        A JUSTIFICATIVA FÁCIL SERIA FALSA. «`sum` depende da ordem e `fsum`
        não» deixou de valer no CPython 3.12, que passou a somar `float` com
        compensação de Neumaier. Nas magnitudes de features normalizadas
        robustas — a casa de ±10 — os dois concordam sempre, e um comentário
        no código dizendo o contrário envelheceria como mentira.
        """
        gerador = random.Random(1)
        for _ in range(2_000):
            termos = [gerador.uniform(-10.0, 10.0) for _ in range(14)]
            assert math.fsum(termos) == sum(termos)
            assert math.fsum(termos) == math.fsum(list(reversed(termos)))

    def test_a_divergencia_existe_em_escalas_EXTREMAS(self) -> None:
        """E é por isso que `fsum` continua sendo a escolha.

        `1e18` E `1e-18` NO MESMO SOMATÓRIO fazem a compensação do `sum` ceder.
        Este dataset nunca produz essa razão de escala — o que o teste prova é
        que a diferença entre as duas funções é real, e que a escolha de `fsum`
        é por CONTRATO (a exatidão é garantia da linguagem) e não por um
        defeito observado nos nossos números.
        """
        termos = [
            -7.674285652675883e16,
            -4.229419612797336e16,
            -1.2099054733174109e17,
            7.59529133345538e-19,
            3.3907899381966855e-19,
            2.4809287974311402e17,
            4.402215171046672e17,
        ]
        assert math.fsum(termos) != sum(termos)
        assert math.fsum(termos) == 4.4828679686130797e17


class TestAsPropriedadesDaDissimilaridade:
    """§109, §110 — as três que valem, e a que NÃO vale."""

    def test_identidade(self) -> None:
        assert distancia().evaluate((1.5, -2.5), (1.5, -2.5)) == 0.0

    def test_nao_negatividade(self) -> None:
        d = distancia()
        for q, c in (((0.0, 0.0), (1.0, 2.0)), ((-3.0, 4.0), (5.0, -6.0))):
            assert d.evaluate(q, c) >= 0.0

    def test_simetria(self) -> None:
        d = distancia()
        assert d.evaluate((1.0, 2.0), (3.0, 5.0)) == d.evaluate((3.0, 5.0), (1.0, 2.0))

    def test_a_desigualdade_triangular_NAO_vale(self) -> None:
        """§110 — e é por isso que o nome é «dissimilaridade», e não «métrica».

        `a=0`, `b=1`, `c=2` no primeiro eixo: `d²(a,c) = 4` e
        `d²(a,b) + d²(b,c) = 1 + 1 = 2`. A desigualdade falha, e afirmá-la
        levaria alguém a podar uma busca com uma cota que não existe.
        """
        d = distancia()
        ac = d.evaluate((0.0, 0.0), (2.0, 0.0))
        ab = d.evaluate((0.0, 0.0), (1.0, 0.0))
        bc = d.evaluate((1.0, 0.0), (2.0, 0.0))
        assert ac > ab + bc

    def test_a_raiz_preservaria_a_desigualdade(self) -> None:
        """O contraste. `sqrt` devolve a métrica — e o ranking é o mesmo."""
        d = distancia()
        ac = math.sqrt(d.evaluate((0.0, 0.0), (2.0, 0.0)))
        ab = math.sqrt(d.evaluate((0.0, 0.0), (1.0, 0.0)))
        bc = math.sqrt(d.evaluate((1.0, 0.0), (2.0, 0.0)))
        assert ac <= ab + bc


class TestAsRecusasDaDistancia:
    """§60 — não finito é corrupção, e não ausência de candidato."""

    @pytest.mark.parametrize("valor", [math.nan, math.inf, -math.inf])
    def test_nao_finito_e_recusado(self, valor: float) -> None:
        with pytest.raises(ValidationError, match="não finito"):
            distancia().evaluate((0.0, 0.0), (valor, 1.0))

    def test_um_vetor_de_tamanho_errado_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="eixos"):
            distancia().evaluate((0.0,), (1.0, 2.0))

    def test_a_representacao_canonica_e_um_roundtrip(self) -> None:
        """§65 — `repr`, e não casas fixas: dois números próximos não colapsam."""
        um, outro = 0.1 + 0.2, 0.30000000000000004
        assert distance_text(um) == distance_text(outro)
        assert distance_text(0.3) != distance_text(0.30000000000000004)
        assert float(distance_text(um)) == um


class TestAPoliticaDeCandidatos:
    """§13 ao §15 — o que ela declara, e o que ela recusa."""

    def test_a_politica_de_producao(self) -> None:
        politica = DEFAULT_CANDIDATE_POLICY
        assert politica.name == "SAME_COMPETITION_REFERENCE_EXACT_TIMEPOINT_V1"
        assert politica.query_split is DatasetSplit.EVALUATION
        assert politica.candidate_split is DatasetSplit.REFERENCE
        assert politica.competition_scope is CompetitionScope.SAME_COMPETITION
        assert politica.time_alignment is TimeAlignmentPolicy.EXACT_MATCH_TIME_POINT
        assert politica.candidate_sampling is CandidateSampling.NONE
        assert politica.candidate_cap is None
        assert politica.excludes_same_match

    def test_a_impressao_e_deterministica(self) -> None:
        assert CandidateUniversePolicy().fingerprint == DEFAULT_CANDIDATE_POLICY.fingerprint

    def test_candidatos_de_avaliacao_sao_recusados(self) -> None:
        with pytest.raises(ValidationError, match="ajudou a definir"):
            CandidateUniversePolicy(
                query_split=DatasetSplit.REFERENCE,
                candidate_split=DatasetSplit.EVALUATION,
            )

    def test_escopo_cruzando_competicoes_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="CROSS_COMPETITION"):
            CandidateUniversePolicy(competition_scope=CompetitionScope.CROSS_COMPETITION)

    def test_as_duas_metades_iguais_sao_recusadas(self) -> None:
        with pytest.raises(ValidationError, match="mesma metade"):
            CandidateUniversePolicy(
                query_split=DatasetSplit.REFERENCE, candidate_split=DatasetSplit.REFERENCE
            )

    def test_o_catalogo_de_inelegibilidade_e_fechado(self) -> None:
        assert {r.name for r in IneligibilityReason} == {
            "INCOMPLETE_PROFILE",
            # O PR-06.2 ACRESCENTOU ESTE MEMBRO, e ele é o irmão afrouxado do
            # primeiro: o candidato compartilha eixos, e não tantos quanto o
            # piso de evidência exige. Ele NÃO é estrutural.
            "INSUFFICIENT_SHARED_COVERAGE",
            # E O PR-06.3 ACRESCENTOU TRÊS, todos de TRAJETÓRIA. Um motivo só
            # esconderia a diferença entre atrição de feature e começo de
            # período, que são fenômenos distintos com causas distintas.
            "INSUFFICIENT_SHARED_TRAJECTORY_CELLS",
            "INSUFFICIENT_SHARED_HORIZONS",
            "INSUFFICIENT_PER_HORIZON_COVERAGE",
            "SAME_MATCH",
            "REPRESENTATION_MISMATCH",
        }

    def test_so_o_perfil_incompleto_NAO_e_estrutural(self) -> None:
        """§73 — o número normal e os defeitos são contados separados."""
        assert not IneligibilityReason.INCOMPLETE_PROFILE.is_structural
        assert IneligibilityReason.SAME_MATCH.is_structural
        assert IneligibilityReason.REPRESENTATION_MISMATCH.is_structural

    def test_os_TRES_motivos_de_trajetoria_NAO_sao_estruturais(self) -> None:
        """§19 do adendo — eles medem ausência de dado, como os irmãos.

        UM CANDIDATO NO COMEÇO DO PERÍODO NÃO É UM DEFEITO DE DATASET. Contá-lo
        entre os estruturais faria a atrição normal parecer corrupção, e é
        exatamente a distinção que o §73 do PR-06.1 existe para preservar.
        """
        assert not IneligibilityReason.INSUFFICIENT_SHARED_TRAJECTORY_CELLS.is_structural
        assert not IneligibilityReason.INSUFFICIENT_SHARED_HORIZONS.is_structural
        assert not IneligibilityReason.INSUFFICIENT_PER_HORIZON_COVERAGE.is_structural


class TestOAlinhamentoTemporal:
    """§16 ao §21 — o instante exato, e as duas componentes que a grade fixa."""

    def test_o_mesmo_instante_alinha(self) -> None:
        um = GridTimePoint.of(Period.FIRST_HALF, 30)
        assert um.aligns_with(GridTimePoint.of(Period.FIRST_HALF, 30))

    def test_o_minuto_vizinho_NAO_alinha(self) -> None:
        """§100 — 29 e 31 não entram numa query do minuto 30."""
        trinta = GridTimePoint.of(Period.FIRST_HALF, 30)
        assert not trinta.aligns_with(GridTimePoint.of(Period.FIRST_HALF, 29))
        assert not trinta.aligns_with(GridTimePoint.of(Period.FIRST_HALF, 31))

    def test_a_fase_diferente_NAO_alinha(self) -> None:
        """§17, §18 — o minuto 30 do primeiro tempo não é o do segundo."""
        assert not GridTimePoint.of(Period.FIRST_HALF, 30).aligns_with(
            GridTimePoint.of(Period.SECOND_HALF, 30)
        )

    def test_o_pre_jogo_so_alinha_com_pre_jogo(self) -> None:
        pre = GridTimePoint.of(Period.PRE_MATCH, 0)
        assert pre.is_pre_match
        assert not pre.aligns_with(GridTimePoint.of(Period.FIRST_HALF, 0))

    def test_a_prorrogacao_alinha_com_prorrogacao(self) -> None:
        """§21 — o mesmo `MatchTimePoint` de prorrogação, e nenhum outro."""
        prorrogacao = GridTimePoint.of(Period.EXTRA_TIME_FIRST, 95)
        assert prorrogacao.aligns_with(GridTimePoint.of(Period.EXTRA_TIME_FIRST, 95))
        assert not prorrogacao.aligns_with(GridTimePoint.of(Period.SECOND_HALF, 95))

    def test_a_ordem_e_a_do_JOGO_e_nao_a_do_texto(self) -> None:
        """`EXTRA_TIME_FIRST` vem depois de `SECOND_HALF`, e antes por texto."""
        assert GridTimePoint.of(Period.SECOND_HALF, 90) < GridTimePoint.of(
            Period.EXTRA_TIME_FIRST, 91
        )

    def test_um_acrescimo_e_recusado_no_alinhamento_de_grade(self) -> None:
        """A grade é de MINUTO: «45+3» não é um corte dela."""
        from sports_intelligence.domain.features.temporal import MatchTimePoint

        with pytest.raises(ValidationError, match="acréscimo"):
            GridTimePoint.from_match_time_point(MatchTimePoint.of(Period.FIRST_HALF, 45, 3))

    def test_um_desempate_e_recusado(self) -> None:
        from sports_intelligence.domain.features.temporal import MatchTimePoint

        with pytest.raises(ValidationError, match="desempate"):
            GridTimePoint.from_match_time_point(
                MatchTimePoint.of(Period.FIRST_HALF, 45, sequence=7)
            )

    def test_a_volta_ao_contrato_completo_traz_as_quatro_componentes(self) -> None:
        posicao = GridTimePoint.of(Period.FIRST_HALF, 30).as_match_time_point()
        assert posicao.period is Period.FIRST_HALF
        assert posicao.minute == 30
        assert posicao.stoppage == GRID_STOPPAGE
        assert not posicao.has_tiebreak

    def test_uma_fase_desconhecida_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="fase desconhecida"):
            GridTimePoint.from_columns(period="TERCEIRO_TEMPO", minute=1)


class TestOPerfil:
    """§42 ao §48 — eixos robustos e ajustados, e nada mais."""

    def _artefato(
        self, chave: str, impressao: str, estado: FitStatus, competicao: CompetitionId
    ) -> NormalizerFitArtifact:
        from decimal import Decimal

        comuns = {
            "feature_key": chave,
            "feature_version": "1.0",
            "feature_fingerprint": impressao,
            "normalizer_key": "competition_median_iqr_reference",
            "normalizer_fingerprint": "n" * 64,
            "competition_id": competicao,
            "source_corpus_fingerprint": "c" * 64,
            "source_space_fingerprint": "s" * 64,
            "population_count": 100,
            "available_count": 100,
            "population_digest": "p" * 64,
            "fit_cutoff": {},
        }
        if estado is FitStatus.FITTED:
            return NormalizerFitArtifact(
                **comuns,  # type: ignore[arg-type]
                status=estado,
                median=Decimal("1"),
                q1=Decimal("0"),
                q3=Decimal("2"),
                iqr=Decimal("2"),
            )
        if estado is FitStatus.DEGENERATE_SCALE:
            return NormalizerFitArtifact(
                **comuns,  # type: ignore[arg-type]
                status=estado,
                median=Decimal("1"),
                q1=Decimal("1"),
                q3=Decimal("1"),
                iqr=Decimal("0"),
            )
        return NormalizerFitArtifact(**comuns, status=estado)  # type: ignore[arg-type]

    def _pacote(
        self, estados: dict[str, FitStatus]
    ) -> tuple[CompetitionNormalizerArtifactBundle, object]:
        plano = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=instant(datetime(2025, 6, 1, tzinfo=UTC))
            )
        )
        competicao = CompetitionId.derive("premier")
        artefatos = [
            self._artefato(chave, plano.transform_of(chave).feature_fingerprint, estado, competicao)
            for chave, estado in estados.items()
        ]
        return (
            CompetitionNormalizerArtifactBundle.of(
                competition=LIGA_A,
                competition_id=competicao,
                reference_fingerprint="r" * 64,
                plan_fingerprint=plano.fingerprint,
                artifacts=artefatos,
            ),
            plano,
        )

    def test_so_os_FITTED_entram(self) -> None:
        """§43, §45, §46, §105 — degenerado e sem amostra ficam de fora."""
        pacote, plano = self._pacote(
            {
                "xg_home_5m": FitStatus.FITTED,
                "xg_away_5m": FitStatus.DEGENERATE_SCALE,
                "xg_home_10m": FitStatus.INSUFFICIENT_SAMPLE,
            }
        )
        resolvido = DEFAULT_RETRIEVAL_PROFILE.resolve(plan=plano, bundle=pacote)  # type: ignore[arg-type]
        assert resolvido.feature_keys == ("xg_home_5m",)
        assert resolvido.axis_count == 1
        assert resolvido.excluded_by_status == {
            FitStatus.DEGENERATE_SCALE.value: 1,
            FitStatus.INSUFFICIENT_SAMPLE.value: 1,
        }

    def test_nenhum_eixo_PASS_THROUGH_entra(self) -> None:
        """§44 — o relógio e as contagens não estão na escala robusta."""
        pacote, plano = self._pacote({"xg_home_5m": FitStatus.FITTED})
        resolvido = DEFAULT_RETRIEVAL_PROFILE.resolve(plan=plano, bundle=pacote)  # type: ignore[arg-type]
        for chave in resolvido.feature_keys:
            assert plano.strategy_of(chave) is TransformStrategy.ROBUST_MEDIAN_IQR  # type: ignore[attr-defined]

    def test_a_ordem_e_a_do_PLANO(self) -> None:
        """Duas resoluções que ordenassem diferente somariam diferente."""
        pacote, plano = self._pacote(
            {"xg_away_5m": FitStatus.FITTED, "xg_home_5m": FitStatus.FITTED}
        )
        resolvido = DEFAULT_RETRIEVAL_PROFILE.resolve(plan=plano, bundle=pacote)  # type: ignore[arg-type]
        do_plano = [
            t.feature_key
            for t in plano.transforms  # type: ignore[attr-defined]
            if t.feature_key in resolvido.feature_keys
        ]
        assert list(resolvido.feature_keys) == do_plano

    def test_um_pacote_sob_outro_plano_e_recusado(self) -> None:
        pacote, _plano = self._pacote({"xg_home_5m": FitStatus.FITTED})
        outro = plan_for(
            reference_end_exclusive_normalizer=causal_dataset_normalizer(
                reference_end_exclusive=instant(datetime(2025, 8, 1, tzinfo=UTC))
            )
        )
        with pytest.raises(ValidationError, match="outro plano"):
            DEFAULT_RETRIEVAL_PROFILE.resolve(plan=outro, bundle=pacote)

    def test_um_perfil_vazio_e_um_estado_valido(self) -> None:
        pacote, plano = self._pacote({"xg_home_5m": FitStatus.DEGENERATE_SCALE})
        resolvido = DEFAULT_RETRIEVAL_PROFILE.resolve(plan=plano, bundle=pacote)  # type: ignore[arg-type]
        assert resolvido.is_empty
        assert resolvido.axis_count == 0

    def test_o_perfil_base_e_diagnostico(self) -> None:
        """§113 — a afirmação está no objeto, e não só na documentação."""
        assert DEFAULT_RETRIEVAL_PROFILE.is_diagnostic
        assert DEFAULT_RETRIEVAL_PROFILE.name == "ROBUST_COMPLETE_CASE_EXACT_BASELINE_V1"
        assert DEFAULT_RETRIEVAL_PROFILE.axis_selection is AxisSelection.ROBUST_FITTED
        assert DEFAULT_RETRIEVAL_PROFILE.missing_policy is MissingPolicy.COMPLETE_CASE
        assert DEFAULT_RETRIEVAL_PROFILE.weight_policy is WeightPolicy.EQUAL

    def test_a_impressao_do_perfil_resolvido_cobre_o_pacote(self) -> None:
        """§47 — dois perfis com os mesmos nomes e artefatos diferentes."""
        um = perfil(bundle_fingerprint="1" * 64)
        outro = perfil(bundle_fingerprint="2" * 64)
        assert um.feature_keys == outro.feature_keys
        assert um.fingerprint != outro.fingerprint

    def test_dois_perfis_diferentes_nao_se_comparam(self) -> None:
        with pytest.raises(ValidationError, match="não se compara"):
            perfil().assert_comparable_with(perfil(eixos=(EIXO_A,)))

    def test_um_eixo_repetido_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="repetido"):
            perfil(eixos=(EIXO_A, EIXO_A))


class TestOsCatalogosFechados:
    """§14, §54, §57 — um método, uma seleção, uma ponderação."""

    def test_a_distancia_tem_um_metodo_so(self) -> None:
        assert {m.value for m in DistanceMethod} == {"EXACT_SQUARED_L2_COMPLETE_CASE_V1"}

    def test_o_perfil_tem_uma_selecao_e_uma_ausencia(self) -> None:
        assert {s.value for s in AxisSelection} == {"ROBUST_FITTED"}
        # DOIS MEMBROS DESDE O PR-06.2, e NENHUM deles imputa. O que continua
        # fora do catálogo é o que importa: `ZERO_FILL`, `MEAN_FILL` e
        # `SHARED_DIMENSIONS` não têm nome aqui, e por isso não podem ser
        # configurados por engano.
        assert {m.value for m in MissingPolicy} == {"COMPLETE_CASE", "AVAILABILITY_AWARE"}
        assert {w.value for w in WeightPolicy} == {"EQUAL"}

    def test_a_distancia_declara_que_e_ao_quadrado(self) -> None:
        """§110 — quem imprime o número tem como perguntar."""
        assert distancia().is_squared


class TestOPedido:
    """§30, §31 — o que o pedido valida."""

    def test_K_menor_que_um_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="não é uma pergunta"):
            pedido(k=0)

    def test_K_acima_do_teto_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="teto operacional"):
            pedido(k=MAX_K + 1)

    def test_K_no_teto_e_aceito(self) -> None:
        assert pedido(k=MAX_K).k == MAX_K

    def test_uma_versao_vazia_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem versão"):
            HistoricalRetrievalQuery(
                dataset_version_id="  ",
                dataset_name="x",
                dataset_version="v1.0",
                representation=pedido().representation,
                key=pedido().key,
                k=1,
            )
