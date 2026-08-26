"""A INVARIANTE central do PR-05.5.2 — o ajuste não enxerga a avaliação.

    ∂ArtifactSet / ∂EVALUATION  =  0

TUDO NESTE PR EXISTE PARA ISSO. O plano explícito, a impressão de referência
separada da global, o pacote por competição, a linhagem fora da identidade: são
todos formas de tornar esta derivada nula por CONSTRUÇÃO, e este arquivo é onde
a construção é conferida.

A FORMA DO TESTE É SEMPRE A MESMA. Dois cenários com a mesma REFERÊNCIA e
avaliações diferentes — em tamanho, em valores, em competição — têm de produzir:

    a mesma impressão de referência         (global e por competição)
    os mesmos artefatos, número a número
    a mesma impressão de pacote
    a mesma impressão de conjunto
    as mesmas linhas normalizadas de REFERÊNCIA, dígito a dígito

E TÊM DE PRODUZIR IMPRESSÕES DIFERENTES onde a diferença é real: a global e a
de avaliação. Um teste que só provasse igualdade passaria com uma implementação
que devolvesse constante.

OS VALORES DA AVALIAÇÃO COMEÇAM EM CEM. Se um deles vazasse para o ajuste, a
mediana da referência — que vive entre 0,5 e 16,5 — saltaria de forma
inconfundível. A invariante falharia por um número, e não por um dígito de hash
que ninguém sabe interpretar.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

import pytest

from sports_intelligence.domain.features.dataset.split import DatasetSplit
from sports_intelligence.domain.features.extraction.catalog_v2 import (
    extended_feature_catalog,
)
from sports_intelligence.domain.features.fitting.artifact import (
    FitStatus,
    NormalizerFitArtifact,
)
from sports_intelligence.domain.features.normalized.artifacts import (
    CompetitionNormalizerArtifactBundle,
    NormalizerArtifactSet,
    build_artifact_set,
)
from sports_intelligence.domain.features.normalized.bridge import float64_bytes
from sports_intelligence.domain.features.normalized.fit import (
    ReferenceFitScan,
    fit_bundles,
)
from sports_intelligence.domain.features.normalized.normalizer import (
    causal_dataset_normalizer,
)
from sports_intelligence.domain.features.normalized.plan import (
    NormalizationPlan,
)
from sports_intelligence.domain.features.normalized.rows import (
    NormalizationAvailability,
    NormalizedContentAccumulator,
    NormalizedContentIdentity,
    NormalizedFeatureRow,
)
from sports_intelligence.domain.features.normalized.transform import (
    RawFeatureRowView,
    RowNormalizer,
)
from sports_intelligence.domain.features.normalized.versions import (
    NormalizedFeatureRepresentationSpec,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ValidationError
from tests.support.normalized_fixtures import (
    COMPETICOES,
    DIVISAO,
    FRONTEIRA,
    LIGA_A,
    LIGA_B,
    avaliacao,
    em_ordem,
    linha,
    plano,
    referencia,
)

pytestmark = pytest.mark.property

EIXO: Final[str] = "xg_home_5m"

ATOR: Final[Actor] = Actor.system("test")


class Cenario:
    """Um dataset inteiro, do ajuste às linhas normalizadas.

    ELE EXISTE PARA QUE A MUTAÇÃO DA AVALIAÇÃO SEJA UMA LINHA. Repetir as seis
    etapas em cada teste esconderia a comparação — que é o que os testes deste
    arquivo afirmam — atrás da montagem.
    """

    def __init__(
        self,
        rows: Sequence[RawFeatureRowView],
        *,
        plan: NormalizationPlan,
    ) -> None:
        self.plan = plan
        self.rows = em_ordem(rows)
        catalogo = extended_feature_catalog()
        definicoes = {spec.definition.key: spec.definition for spec in catalogo.specs}

        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        for view in self.rows:
            if view.split is DatasetSplit.REFERENCE:
                varredura.observe(view)
        self.reference = varredura.reference_identity()
        self.bundles: tuple[CompetitionNormalizerArtifactBundle, ...] = fit_bundles(
            varredura,
            normalizer=causal_dataset_normalizer(reference_end_exclusive=FRONTEIRA),
            plan=plan,
            definitions=definicoes,
            reference=self.reference,
        )
        self.artifact_set: NormalizerArtifactSet = build_artifact_set(
            plan_fingerprint=plan.fingerprint,
            split_fingerprint=DIVISAO,
            reference_end_exclusive=FRONTEIRA,
            reference=self.reference,
            bundles=self.bundles,
            at=FRONTEIRA,
            created_by=ATOR,
            source_version_id="qualquer",
            source_raw_content_fingerprint="f" * 64,
        )
        self.representation = NormalizedFeatureRepresentationSpec.of(
            plan=plan,
            artifact_set_id=self.artifact_set.id,
            artifact_set_fingerprint=self.artifact_set.fingerprint,
        )
        normalizador = RowNormalizer(
            plan=plan,
            artifact_set=self.artifact_set,
            representation=self.representation,
        )
        acumulador = NormalizedContentAccumulator(
            representation_fingerprint=self.representation.fingerprint,
            plan_fingerprint=plan.fingerprint,
            artifact_set_fingerprint=self.artifact_set.fingerprint,
        )
        self.normalized = [normalizador.normalize(view) for view in self.rows]
        for row in self.normalized:
            acumulador.update(row)
        self.content: NormalizedContentIdentity = acumulador.finalize()

    def bundle(self, competition: str) -> CompetitionNormalizerArtifactBundle:
        return self.artifact_set.bundle_of(competition)

    def artifact(self, competition: str, feature_key: str = EIXO) -> NormalizerFitArtifact:
        return self.bundle(competition).artifact_of(feature_key)

    def reference_rows(self) -> list[NormalizedFeatureRow]:
        return [r for r in self.normalized if r.split is DatasetSplit.REFERENCE]


@pytest.fixture(scope="module")
def plan() -> NormalizationPlan:
    return plano()


@pytest.fixture(scope="module")
def pequeno(plan: NormalizationPlan) -> Cenario:
    """Referência fixa + uma avaliação de cinco partidas."""
    return Cenario([*referencia(plan=plan), *avaliacao(matches=5, plan=plan)], plan=plan)


@pytest.fixture(scope="module")
def grande(plan: NormalizationPlan) -> Cenario:
    """A MESMA referência + uma avaliação de sessenta partidas, com outros
    valores. Só a segunda metade mudou."""
    return Cenario(
        [*referencia(plan=plan), *avaliacao(matches=60, semente=500.0, plan=plan)],
        plan=plan,
    )


class TestADerivadaEhNula:
    """§4, §46, §152 — mexer na avaliação não muda ajuste nenhum."""

    def test_a_impressao_de_referencia_nao_muda(self, pequeno: Cenario, grande: Cenario) -> None:
        assert pequeno.reference.fingerprint == grande.reference.fingerprint
        assert pequeno.reference.rows == grande.reference.rows
        assert dict(pequeno.reference.by_competition) == dict(grande.reference.by_competition)

    def test_os_artefatos_sao_os_mesmos_numero_a_numero(
        self, pequeno: Cenario, grande: Cenario
    ) -> None:
        a = pequeno.bundle(LIGA_A).artifact_of(EIXO)
        b = grande.bundle(LIGA_A).artifact_of(EIXO)
        assert a.status is FitStatus.FITTED, "o cenário precisa ajustar de verdade"
        assert (a.median, a.q1, a.q3, a.iqr) == (b.median, b.q1, b.q3, b.iqr)
        assert a.population_count == b.population_count
        assert a.available_count == b.available_count
        assert a.population_digest == b.population_digest
        assert a.fingerprint == b.fingerprint

    def test_a_impressao_do_pacote_nao_muda(self, pequeno: Cenario, grande: Cenario) -> None:
        assert pequeno.bundle(LIGA_A).fingerprint == grande.bundle(LIGA_A).fingerprint

    def test_a_impressao_do_conjunto_nao_muda(self, pequeno: Cenario, grande: Cenario) -> None:
        assert pequeno.artifact_set.fingerprint == grande.artifact_set.fingerprint

    def test_a_linhagem_muda_e_fica_fora_da_identidade(
        self, pequeno: Cenario, grande: Cenario
    ) -> None:
        """A avaliação existe, e é RASTREÁVEL — só não é IDENTIDADE (§47)."""
        assert pequeno.artifact_set.lineage()["reference_rows"] == pequeno.reference.rows
        assert pequeno.artifact_set.as_canonical() == grande.artifact_set.as_canonical()
        assert "source_raw_content_fingerprint" not in pequeno.artifact_set.as_canonical()

    def test_as_linhas_normalizadas_de_referencia_sao_identicas(
        self, pequeno: Cenario, grande: Cenario
    ) -> None:
        digestos_a = [r.digest for r in pequeno.reference_rows()]
        digestos_b = [r.digest for r in grande.reference_rows()]
        assert digestos_a == digestos_b

    def test_a_impressao_normalizada_de_referencia_nao_muda(
        self, pequeno: Cenario, grande: Cenario
    ) -> None:
        assert pequeno.content.reference_fingerprint == grande.content.reference_fingerprint

    def test_e_a_global_e_a_de_avaliacao_MUDAM(self, pequeno: Cenario, grande: Cenario) -> None:
        """O outro lado (§154). Um teste que só provasse igualdade passaria com
        uma implementação que devolvesse constante."""
        assert pequeno.content.fingerprint != grande.content.fingerprint
        assert pequeno.content.evaluation_fingerprint != grande.content.evaluation_fingerprint

    def test_a_avaliacao_absurda_nao_deslocou_a_mediana(self, grande: Cenario) -> None:
        """O sentinela. A referência vive entre 0,5 e 16,5; a avaliação começa
        em 500. Uma mediana acima de 20 é vazamento, e não arredondamento."""
        artefato = grande.bundle(LIGA_A).artifact_of(EIXO)
        assert artefato.median is not None
        assert artefato.median < 20


class TestOAjusteRecusaAAvaliacao:
    """§29, §30 — a exclusão é uma RECUSA, e não um filtro silencioso."""

    def test_uma_linha_de_avaliacao_no_ajuste_levanta(self, plan: NormalizationPlan) -> None:
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        with pytest.raises(ValidationError, match="somente sobre REFER"):
            varredura.observe(avaliacao(matches=1, plan=plan)[0])

    def test_uma_linha_fora_de_ordem_levanta(self, plan: NormalizationPlan) -> None:
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        linhas = referencia(matches=3, plan=plan)
        varredura.observe(linhas[1])
        with pytest.raises(ValidationError, match=r"ordenada|em ordem"):
            varredura.observe(linhas[0])


class TestOIsolamentoEntreCompeticoes:
    """§8 — mexer na La Liga não muda o que a Premier League afirma."""

    def test_a_referencia_de_uma_liga_nao_muda_o_pacote_da_outra(
        self, plan: NormalizationPlan
    ) -> None:
        base_a = referencia(competition=LIGA_A, plan=plan)
        um = Cenario([*base_a, *referencia(competition=LIGA_B, plan=plan)], plan=plan)
        outro = Cenario(
            [
                *base_a,
                *referencia(competition=LIGA_B, deslocamento=250.0, plan=plan),
            ],
            plan=plan,
        )
        assert um.bundle(LIGA_A).fingerprint == outro.bundle(LIGA_A).fingerprint
        assert um.bundle(LIGA_B).fingerprint != outro.bundle(LIGA_B).fingerprint
        # E o conjunto MUDA, porque uma das competições mudou de verdade.
        assert um.artifact_set.fingerprint != outro.artifact_set.fingerprint

    def test_uma_competicao_so_de_avaliacao_normaliza_sem_artefato(
        self, plan: NormalizationPlan
    ) -> None:
        """§87 — a linha continua existindo, com o motivo dizendo por quê."""
        cenario = Cenario(
            [
                *referencia(competition=LIGA_A, plan=plan),
                *avaliacao(matches=3, competition=LIGA_B, plan=plan),
            ],
            plan=plan,
        )
        forasteiras = [r for r in cenario.normalized if r.competition == LIGA_B]
        assert forasteiras, "o cenário precisa ter linhas da liga sem referência"
        celula = forasteiras[0].cell_of(EIXO)
        assert (
            celula.availability is NormalizationAvailability.ARTIFACT_NOT_AVAILABLE_FOR_COMPETITION
        )
        assert celula.value is None


class TestOPassThroughEhExato:
    """§78 — o mesmo `float64`, bit a bit, sem passar por `Decimal`."""

    def test_um_eixo_pass_through_sai_com_o_mesmo_numero(self, plan: NormalizationPlan) -> None:
        chave = plan.pass_through_keys[0]
        # `0.1 + 0.2` é `0.30000000000000004`. Um caminho que passasse por
        # `Decimal(str(x))` devolveria `0.3`, e a diferença apareceria aqui.
        valor = 0.1 + 0.2
        extra = linha(
            match="premier-eva-999",
            grid_index=0,
            split=DatasetSplit.EVALUATION,
            valores={EIXO: 1.0, chave: valor},
            plan=plan,
        )
        cenario = Cenario([*referencia(plan=plan), extra], plan=plan)
        alvo = next(r for r in cenario.normalized if r.key.match_key == "premier-eva-999")
        celula = alvo.cell_of(chave)
        assert celula.availability is NormalizationAvailability.AVAILABLE
        assert celula.value is not None
        assert float64_bytes(celula.value) == float64_bytes(valor)


class TestNaoHaFallback:
    """§88, ADR-0035 — um eixo ROBUST degenerado NÃO vira PASS_THROUGH."""

    def test_iqr_nulo_produz_celula_vazia_e_nao_o_valor_cru(self, plan: NormalizationPlan) -> None:
        # Uma referência CONSTANTE: todos os quartis coincidem, e não há
        # dispersão pela qual dividir.
        constantes = [
            linha(
                match=f"premier-ref-{i:03d}",
                grid_index=0,
                split=DatasetSplit.REFERENCE,
                valores={EIXO: 2.0},
                plan=plan,
            )
            for i in range(40)
        ]
        alvo = linha(
            match="premier-eva-001",
            grid_index=0,
            split=DatasetSplit.EVALUATION,
            valores={EIXO: 7.5},
            plan=plan,
        )
        cenario = Cenario([*constantes, alvo], plan=plan)
        artefato = cenario.bundle(LIGA_A).artifact_of(EIXO)
        assert artefato.status is FitStatus.DEGENERATE_SCALE
        assert artefato.iqr == 0

        celula = cenario.normalized[-1].cell_of(EIXO)
        assert celula.availability is NormalizationAvailability.ARTIFACT_DEGENERATE_SCALE
        assert celula.value is None, (
            "o valor cru NÃO passa direto: a coluna teria unidades misturadas"
        )

    def test_amostra_insuficiente_tambem_nao_cai_para_o_cru(self, plan: NormalizationPlan) -> None:
        cenario = Cenario(
            [
                *referencia(matches=5, plan=plan),
                linha(
                    match="premier-eva-001",
                    grid_index=0,
                    split=DatasetSplit.EVALUATION,
                    valores={EIXO: 3.0},
                    plan=plan,
                ),
            ],
            plan=plan,
        )
        artefato = cenario.bundle(LIGA_A).artifact_of(EIXO)
        assert artefato.status is FitStatus.INSUFFICIENT_SAMPLE
        celula = cenario.normalized[-1].cell_of(EIXO)
        assert celula.availability is NormalizationAvailability.ARTIFACT_INSUFFICIENT_SAMPLES
        assert celula.value is None


class TestADeterminismoDeOrdemEDeLote:
    """§155 — a linha normalizada não depende de com quem ela foi lida."""

    def test_normalizar_em_lotes_diferentes_da_a_mesma_linha(
        self, pequeno: Cenario, plan: NormalizationPlan
    ) -> None:
        normalizador = RowNormalizer(
            plan=plan,
            artifact_set=pequeno.artifact_set,
            representation=pequeno.representation,
        )
        # A MESMA linha, normalizada por um objeto que nunca viu as outras.
        sozinha = normalizador.normalize(pequeno.rows[7])
        assert sozinha.digest == pequeno.normalized[7].digest

    def test_a_impressao_recusa_a_ordem_invertida(self, pequeno: Cenario) -> None:
        acumulador = NormalizedContentAccumulator(
            representation_fingerprint=pequeno.representation.fingerprint,
            plan_fingerprint=pequeno.plan.fingerprint,
            artifact_set_fingerprint=pequeno.artifact_set.fingerprint,
        )
        acumulador.update(pequeno.normalized[1])
        with pytest.raises(ValidationError, match="ordenada"):
            acumulador.update(pequeno.normalized[0])


class TestOContrato1Para1:
    """§94 — toda linha crua tem exatamente uma normalizada."""

    def test_a_cardinalidade_e_a_ordem_se_preservam(self, pequeno: Cenario) -> None:
        assert len(pequeno.normalized) == len(pequeno.rows)
        assert [r.key for r in pequeno.normalized] == [v.key for v in pequeno.rows]

    def test_toda_linha_tem_todos_os_eixos_do_plano(self, pequeno: Cenario) -> None:
        esperados = tuple(t.feature_key for t in pequeno.plan.transforms)
        for row in pequeno.normalized:
            assert tuple(c.feature_key for c in row.cells) == esperados

    def test_a_linha_aponta_para_a_crua_pelo_digesto(self, pequeno: Cenario) -> None:
        for crua, normalizada in zip(pequeno.rows, pequeno.normalized, strict=True):
            assert normalizada.source_row_digest == crua.row_digest


class TestAOrdemCanonicaEhDeParticao:
    """A regra que o benchmark corrigiu — e o que ela continua pegando.

    A PRIMEIRA VERSÃO EXIGIA CHAVE GLOBALMENTE CRESCENTE, e isso é falso num
    dataset particionado: as partidas são `uuid5`, então as chaves de duas
    competições se intercalam. O que vale é a ordem de PARTIÇÃO, e depois a de
    chave dentro dela.
    """

    def test_duas_competicoes_intercaladas_por_chave_sao_aceitas(
        self, plan: NormalizationPlan
    ) -> None:
        """O fluxo que a versão anterior recusava, e que é o de produção."""
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        # LALIGA vem antes de PREMIER na ordem de partição, e as chaves das
        # duas se intercalam: `laliga-ref-039` > `premier-ref-000` como texto.
        for view in referencia(matches=40, competition=LIGA_B, plan=plan):
            varredura.observe(view)
        for view in referencia(matches=40, competition=LIGA_A, plan=plan):
            varredura.observe(view)
        assert varredura.rows == 80
        assert varredura.competitions == (LIGA_B, LIGA_A) or set(varredura.competitions) == {
            LIGA_A,
            LIGA_B,
        }

    def test_voltar_a_uma_particao_fechada_e_recusado(self, plan: NormalizationPlan) -> None:
        """É como duas leituras concorrentes se misturariam."""
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        b = referencia(matches=3, competition=LIGA_B, plan=plan)
        a = referencia(matches=3, competition=LIGA_A, plan=plan)
        varredura.observe(b[0])
        varredura.observe(a[0])
        with pytest.raises(ValidationError, match="partição"):
            varredura.observe(b[1])

    def test_a_inversao_DENTRO_de_uma_particao_continua_recusada(
        self, plan: NormalizationPlan
    ) -> None:
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        linhas = referencia(matches=3, plan=plan)
        varredura.observe(linhas[1])
        with pytest.raises(ValidationError, match="linha"):
            varredura.observe(linhas[0])

    def test_a_mesma_linha_duas_vezes_e_recusada(self, plan: NormalizationPlan) -> None:
        """PR-05.4 §107 — ela deslocaria a mediana em direção a si mesma."""
        varredura = ReferenceFitScan(plan=plan, split_fingerprint=DIVISAO, competitions=COMPETICOES)
        uma = referencia(matches=1, plan=plan)[0]
        varredura.observe(uma)
        with pytest.raises(ValidationError, match="linha"):
            varredura.observe(uma)
