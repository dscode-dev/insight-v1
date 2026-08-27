"""Os goldens da distância ciente de disponibilidade — calculados à mão.

TODO NÚMERO ESPERADO AQUI CABE NUMA LINHA DE CONTA. Se um destes testes falhar,
ninguém precisa recalcular nada: `m = 5`, `q = [0,0,0,0,0]`, dois eixos
ausentes e discrepância zero dão `D = 2/5 = 0,4`, e o teste diz isso por
extenso.

    §141   3 de 5 compartilhados, discrepância 0, 2 ausentes   D = 0,4
    §142   2 de 5 compartilhados                               INELEGÍVEL
    §143   5 de 5, todas as diferenças 1                       D = 1,0
    §144   3 compartilhados com δ = [1,2,0], 2 ausentes        D = 1,4

UMA RESSALVA SOBRE O §141 E O §144, e ela é um conflito da própria
especificação. Os dois descrevem um par com TRÊS eixos compartilhados sobre um
perfil de cinco, e o §141 o anota como «elegível exatamente no limiar». Mas o
§21 fixa o mínimo ABSOLUTO em quatro eixos, e o §88 diz por extenso
`shared_count = 3 → ineligible`. Com `m = 5` as duas afirmações não podem valer
juntas: a razão `3/5` admite, e o mínimo de quatro recusa.

    a implementação segue o §21 e o §88. Eles são normativos, concordam entre
    si, e o §186 lista «below-floor candidate receiving distance» como blocker
    absoluto — enquanto a anotação do §141 é a legenda de um exemplo.

Por isso a ARITMÉTICA dos dois goldens é verificada direto na definição de
distância, que não decide elegibilidade, e a elegibilidade tem testes próprios.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator

import pytest

from sports_intelligence.domain.retrieval.availability import (
    AvailabilityInconsistencyError,
    availability_mask,
    count,
    mask_text,
    shared_mask,
    unselected,
)
from sports_intelligence.domain.retrieval.availability_distance import (
    FIXED_PROFILE_DENOMINATOR_V1,
    MISSING_AXIS_PENALTY,
    MISSING_AXIS_PENALTY_SQUARED_IQR_V1,
    AvailabilityAwareDistanceDefinition,
    AvailabilityDistanceMethod,
)
from sports_intelligence.domain.retrieval.availability_result import (
    AvailabilityAwareRetrievalResult,
)
from sports_intelligence.domain.retrieval.candidate import CandidateRow
from sports_intelligence.domain.retrieval.candidate_policy import (
    DEFAULT_CANDIDATE_POLICY,
    IneligibilityReason,
)
from sports_intelligence.domain.retrieval.coverage import (
    DEFAULT_COVERAGE_POLICY,
    MINIMUM_EVIDENCE_COVERAGE_V1,
    AvailabilityCoveragePolicy,
    CoverageAssessment,
    ProfileInsufficientEvidenceError,
    QueryInsufficientCoverageError,
    RationalFloor,
    coverage_summary,
)
from sports_intelligence.domain.retrieval.distance import (
    FLOAT_SEMANTICS_V1,
    DistanceDefinition,
)
from sports_intelligence.domain.retrieval.evidence import (
    DistanceContribution,
    evidence_summary,
)
from sports_intelligence.domain.retrieval.exact import ExactHistoricalRetriever
from sports_intelligence.domain.retrieval.profile import (
    AVAILABILITY_AWARE_RETRIEVAL_PROFILE,
    DEFAULT_RETRIEVAL_PROFILE,
    ROBUST_AVAILABILITY_AWARE_EXACT_V1,
    MissingPolicy,
)
from sports_intelligence.domain.retrieval.query import QuerySnapshot
from sports_intelligence.domain.shared.errors import ValidationError
from tests.support.availability_fixtures import (
    CINCO_EIXOS,
    DEZ_EIXOS,
    candidato_ciente,
    consulta_ciente,
    distancia_ciente,
    pedido_ciente,
    perfil_ciente,
    primeiros,
    recuperador,
)
from tests.support.retrieval_fixtures import DISPONIVEL, SEM_ESCALA, perfil

DISTANCIA = distancia_ciente()
REFERENCIA = "r" * 64


def _recuperar(
    candidatos: Iterable[CandidateRow],
    *,
    k: int = 3,
    snapshot: QuerySnapshot | None = None,
) -> AvailabilityAwareRetrievalResult:
    return recuperador().retrieve(
        query=pedido_ciente(k=k),
        snapshot=snapshot or consulta_ciente(),
        candidates=candidatos,
        reference_content_fingerprint=REFERENCIA,
    )


def _com_dez(candidatos: Iterable[CandidateRow], *, k: int = 3) -> AvailabilityAwareRetrievalResult:
    """A varredura sobre o perfil de DEZ eixos, onde a razão decide."""
    return recuperador(profile=perfil_ciente(eixos=DEZ_EIXOS)).retrieve(
        query=pedido_ciente(k=k),
        snapshot=consulta_ciente(valores=dict.fromkeys(DEZ_EIXOS, 0.0)),
        candidates=candidatos,
        reference_content_fingerprint=REFERENCIA,
    )


# ================================================= os goldens à mão ==


class TestOsGoldensCalculadosAMao:
    """§141 ao §144 — quatro contas que cabem numa linha."""

    def test_141_tres_de_cinco_sem_discrepancia_da_dois_quintos(self) -> None:
        """`Observed = 0`, `Missing = 2`, `m = 5` → `D = 2/5 = 0,4`."""
        conta = DISTANCIA.evaluate(
            (0.0, 0.0, 0.0, None, None),
            (0.0, 0.0, 0.0, None, None),
            (True, True, True, False, False),
        )
        assert conta.observed_squared_sum == 0.0
        assert conta.missing_penalty_sum == 2.0
        assert conta.value == 0.4
        # A INCERTEZA É O NUMERADOR INTEIRO: a discrepância observada foi zero.
        assert conta.penalty_share == 1.0

    def test_141_o_mesmo_candidato_NAO_e_elegivel(self) -> None:
        """§21, §88 — três eixos não passam do mínimo absoluto de quatro."""
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(3))])
        assert resultado.is_empty
        assert resultado.coverage_ineligible_count == 1

    def test_141_com_quatro_eixos_ele_entra_e_fica_no_piso(self) -> None:
        """Um eixo a mais, e o mesmo candidato passa — no piso, pelo mínimo."""
        vizinho = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))]).neighbors[0]
        assert vizinho.dissimilarity == 0.2
        assert vizinho.shared_count == 4
        assert vizinho.is_at_coverage_floor
        assert vizinho.penalty_share == 1.0

    def test_142_dois_de_cinco_nao_recebe_distancia(self) -> None:
        """`s = 2` viola os DOIS pisos — o absoluto e o relativo."""
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(2))])

        assert resultado.is_empty
        assert resultado.universe_count == 1
        assert resultado.coverage_eligible_count == 0
        assert resultado.coverage_ineligible_count == 1
        assert resultado.ineligible == {IneligibilityReason.INSUFFICIENT_SHARED_COVERAGE.value: 1}

    def test_143_caso_completo_com_diferenca_um_da_exatamente_um(self) -> None:
        """`q=[0]*5`, `c=[1]*5`: `d² = 5` no PR-06.1, e `D = 5/5 = 1`."""
        valores = dict.fromkeys(CINCO_EIXOS, 1.0)
        vizinho = _recuperar([candidato_ciente(match="ref-a", valores=valores)]).neighbors[0]

        assert vizinho.dissimilarity == 1.0
        assert vizinho.evidence.observed_squared_sum == 5.0
        assert vizinho.evidence.missing_penalty_sum == 0.0
        assert vizinho.is_complete_case
        # A EQUIVALÊNCIA COM O PR-06.1, no número: `D = d²/m`.
        oraculo = DistanceDefinition(profile=perfil(eixos=CINCO_EIXOS))
        assert oraculo.evaluate((0.0,) * 5, (1.0,) * 5) == 5.0
        assert vizinho.dissimilarity == 5.0 / 5

    def test_144_observado_mais_ausente(self) -> None:
        """δ = [1, 2, 0] e 2 ausentes: `(1+4+0) + 2 = 7`, e `7/5 = 1,4`."""
        conta = DISTANCIA.evaluate(
            (0.0, 0.0, 0.0, None, None),
            (1.0, 2.0, 0.0, None, None),
            (True, True, True, False, False),
        )
        assert conta.observed_squared_sum == 5.0
        assert conta.missing_penalty_sum == 2.0
        assert conta.value == 1.4
        # O MSE OBSERVADO É OUTRO NÚMERO, e diz outra coisa: 5/3 sobre os três
        # eixos que existiam, e não 7/5 sobre o perfil.
        assert conta.observed_mse == 5.0 / 3
        assert conta.penalty_share == 2.0 / 7

    def test_144_na_varredura_com_quatro_eixos(self) -> None:
        """A mesma forma, elegível: δ = [1,2,0,0] e 1 ausente → `6/5 = 1,2`."""
        valores = {
            CINCO_EIXOS[0]: 1.0,
            CINCO_EIXOS[1]: 2.0,
            CINCO_EIXOS[2]: 0.0,
            CINCO_EIXOS[3]: 0.0,
        }
        vizinho = _recuperar([candidato_ciente(match="ref-a", valores=valores)]).neighbors[0]
        assert vizinho.evidence.observed_squared_sum == 5.0
        assert vizinho.evidence.missing_penalty_sum == 1.0
        assert vizinho.dissimilarity == 1.2
        assert vizinho.evidence.observed_mse == 5.0 / 4


# ================================================= a fronteira ==


class TestAFronteiraDoPiso:
    """§87, §88 — a comparabilidade muda de lado com UM eixo."""

    @pytest.mark.parametrize(
        ("compartilhados", "elegivel"),
        [(5, True), (4, True), (3, False), (2, False), (1, False), (0, False)],
    )
    def test_com_cinco_eixos_o_MINIMO_ABSOLUTO_decide(
        self, compartilhados: int, elegivel: bool
    ) -> None:
        """`m = 5`: a razão admitiria `s = 3`, e o mínimo de quatro recusa."""
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(compartilhados))])
        assert (resultado.coverage_eligible_count == 1) is elegivel

    @pytest.mark.parametrize(
        ("compartilhados", "elegivel"),
        [(10, True), (8, True), (6, True), (5, False), (4, False)],
    )
    def test_com_dez_eixos_a_RAZAO_decide(self, compartilhados: int, elegivel: bool) -> None:
        """`m = 10`: o mínimo de quatro já passou, e `3/5` corta em seis."""
        resultado = _com_dez(
            [candidato_ciente(match="ref-a", valores=primeiros(compartilhados, eixos=DEZ_EIXOS))]
        )
        assert (resultado.coverage_eligible_count == 1) is elegivel

    def test_seis_de_dez_esta_EXATAMENTE_no_piso_da_razao(self) -> None:
        """§87 — `5·6 = 30 = 3·10`. A igualdade ADMITE."""
        vizinho = _com_dez(
            [candidato_ciente(match="ref-a", valores=primeiros(6, eixos=DEZ_EIXOS))]
        ).neighbors[0]
        assert vizinho.shared_count == 6
        assert vizinho.is_at_coverage_floor
        assert vizinho.dissimilarity == 0.4

    def test_a_igualdade_exata_admite_e_um_a_menos_nao(self) -> None:
        """`5s = 3m` → elegível. `5s < 3m` → não."""
        politica = DEFAULT_COVERAGE_POLICY
        assert politica.admits_pair(shared=9, profile_axes=15)  # 45 == 45
        assert not politica.admits_pair(shared=8, profile_axes=15)  # 40 < 45

    def test_o_minimo_absoluto_ganha_da_razao(self) -> None:
        """`m = 4`, `s = 3`: a razão passa (15 ≥ 12) e o mínimo recusa.

        OS DOIS PISOS SÃO NECESSÁRIOS, e este é o caso que prova. Sem o mínimo
        absoluto, um perfil pequeno admitiria comparações sobre três eixos.
        """
        politica = DEFAULT_COVERAGE_POLICY
        assert politica.shared_coverage_floor.admits(part=3, whole=4)
        assert not politica.admits_pair(shared=3, profile_axes=4)
        assert politica.admits_pair(shared=4, profile_axes=4)

    def test_a_razao_ganha_do_minimo_quando_o_perfil_e_grande(self) -> None:
        """`m = 20`, `s = 4`: o mínimo passa e a razão recusa (20 < 60)."""
        politica = DEFAULT_COVERAGE_POLICY
        assert not politica.admits_pair(shared=4, profile_axes=20)
        assert politica.admits_pair(shared=12, profile_axes=20)


class TestOPisoERacional:
    """§22, §23 — e a justificativa fácil é falsa."""

    def test_a_comparacao_e_inteira(self) -> None:
        piso = RationalFloor(3, 5)
        assert piso.admits(part=3, whole=5)
        assert piso.admits(part=9, whole=15)
        assert piso.admits(part=6, whole=10)
        assert not piso.admits(part=8, whole=15)

    def test_a_versao_em_float_CONCORDA_e_nao_e_esse_o_motivo(self) -> None:
        """A MEDIÇÃO, e ela desmente a justificativa fácil.

        A JUSTIFICATIVA FÁCIL SERIA «`0.6` não existe em `float64`, logo a
        comparação erra na fronteira». Ela é FALSA, e este teste é a medição
        que a desmente: sobre todo `m` até dez mil, e nos pontos que cercam a
        fronteira, o resultado em ponto flutuante coincide com o exato em TODOS
        os casos.

        O MOTIVO REAL DA ARITMÉTICA INTEIRA está no cabeçalho de `coverage.py`:
        ela é exata por construção, e a versão em `float` é correta sob um
        argumento sobre arredondamento que teria de ser refeito a cada mudança
        de piso. Este teste É esse argumento — e mantê-lo por perto é o que
        torna honesta a escolha de não depender dele.
        """
        piso = RationalFloor(3, 5)
        divergencias = [
            (s, m)
            for m in range(1, 10_001)
            for s in sorted({0, (3 * m) // 5, (3 * m) // 5 + 1, m})
            if 0 <= s <= m and piso.admits(part=s, whole=m) != ((s / m) >= 0.6)
        ]
        assert divergencias == []
        # E NA FRONTEIRA EXATA os dois lados são o MESMO `float64`.
        assert (3 / 5) == 0.6
        assert (9 / 15) == 0.6
        assert (12 / 20) == 0.6

    def test_o_piso_nao_pode_passar_de_um(self) -> None:
        with pytest.raises(ValidationError, match="acima de 1"):
            RationalFloor(6, 5)

    def test_o_piso_de_um_inteiro_e_o_caso_completo(self) -> None:
        piso = RationalFloor(1, 1)
        assert piso.admits(part=5, whole=5)
        assert not piso.admits(part=4, whole=5)


# ================================================= a semântica da ausência ==


class TestAusenciaNaoEhZero:
    """§3, §43, §46, §94 — o princípio, provado em várias formas."""

    def test_ausente_e_diferente_de_valor_igual(self) -> None:
        """Um eixo ausente custa `1/m`; um eixo igual custa zero."""
        completo = _recuperar([candidato_ciente(match="ref-a")]).neighbors[0]
        com_um_ausente = _recuperar(
            [candidato_ciente(match="ref-a", valores=primeiros(4))]
        ).neighbors[0]

        assert completo.dissimilarity == 0.0
        assert com_um_ausente.dissimilarity == 1.0 / 5
        assert com_um_ausente.dissimilarity > completo.dissimilarity

    def test_a_evidencia_substitui_a_incerteza(self) -> None:
        """§44 — o eixo revelado e IGUAL faz a contribuição cair de 1 para 0."""
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-a", valores=primeiros(4)),
                candidato_ciente(match="ref-b", valores=primeiros(5)),
            ]
        )
        por_chave = {v.key.match_key: v for v in resultado.neighbors}
        assert por_chave["ref-b"].dissimilarity == 0.0
        assert por_chave["ref-a"].dissimilarity == 0.2
        assert por_chave["ref-b"].rank < por_chave["ref-a"].rank
        # A DIFERENÇA É EXATAMENTE `1/m`.
        assert por_chave["ref-a"].dissimilarity - por_chave["ref-b"].dissimilarity == 1 / 5

    def test_a_evidencia_desfavoravel_PIORA_o_candidato(self) -> None:
        """§45, §92 — e isso é a semântica certa, e não um defeito.

        Revelar um eixo com `δ = 2` custa `4` no lugar de `1`. O candidato cai
        no ranking, e tem de cair: descobrir que dois estados diferem em dois
        IQRs é informação, e ela vale mais que a suposição que ocupava aquele
        lugar.
        """
        oculto = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        revelado = _recuperar(
            [candidato_ciente(match="ref-a", valores={**primeiros(4), CINCO_EIXOS[4]: 2.0})]
        )
        assert oculto.neighbors[0].dissimilarity == 1 / 5
        assert revelado.neighbors[0].dissimilarity == 4 / 5
        assert revelado.neighbors[0].dissimilarity > oculto.neighbors[0].dissimilarity

    def test_a_troca_e_neutra_em_delta_igual_a_um(self) -> None:
        """`|δ| = 1` é o ponto em que evidência e incerteza empatam."""
        revelado = _recuperar(
            [candidato_ciente(match="ref-a", valores={**primeiros(4), CINCO_EIXOS[4]: 1.0})]
        )
        assert revelado.neighbors[0].dissimilarity == 1 / 5

    def test_ambos_ausentes_continuam_custando(self) -> None:
        """§46, §93 — dois desconhecidos não são evidência de igualdade."""
        resultado = _recuperar(
            [candidato_ciente(match="ref-a", valores=primeiros(4))],
            snapshot=consulta_ciente(valores=primeiros(4)),
        )
        vizinho = resultado.neighbors[0]
        assert vizinho.shared_count == 4
        assert vizinho.evidence.missing_penalty_sum == 1.0
        assert vizinho.dissimilarity == 1 / 5
        assert vizinho.evidence.query_mask == "11110"
        assert vizinho.evidence.candidate_mask == "11110"
        assert vizinho.evidence.shared_mask == "11110"

    def test_o_candidato_quase_vazio_nunca_ocupa_o_primeiro_lugar(self) -> None:
        """§28 — o sentinela. Um eixo compartilhado, e ele é EXATO.

        SE A ELEGIBILIDADE FOSSE FROUXA, este candidato teria discrepância
        observada zero e ganharia de todo mundo. Ele é recusado ANTES de
        receber distância.
        """
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-vazio", valores=primeiros(1)),
                candidato_ciente(match="ref-cheio", valores=dict.fromkeys(CINCO_EIXOS, 3.0)),
            ]
        )
        assert resultado.returned_k == 1
        assert resultado.neighbors[0].key.match_key == "ref-cheio"
        assert resultado.coverage_ineligible_count == 1

    def test_imputar_zero_mudaria_o_ranking(self) -> None:
        """§94 — a prova de que a implementação NÃO imputa.

        O CENÁRIO É CONSTRUÍDO PARA QUE A IMPUTAÇÃO SEJA VISÍVEL. A query é
        toda zero. `ref-oco` tem quatro eixos exatos e um ausente; se o ausente
        virasse zero, ele teria `d² = 0` e seria o primeiro. `ref-medido` tem
        os cinco eixos, com discrepância pequena em cada um.
        """
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-oco", valores=primeiros(4)),
                candidato_ciente(match="ref-medido", valores=dict.fromkeys(CINCO_EIXOS, 0.2)),
            ]
        )
        por_chave = {v.key.match_key: v for v in resultado.neighbors}
        # COM IMPUTAÇÃO POR ZERO, `ref-oco` valeria 0,0 e seria o primeiro.
        assert por_chave["ref-oco"].dissimilarity == 0.2
        assert por_chave["ref-medido"].dissimilarity == pytest.approx(0.04)
        assert por_chave["ref-medido"].rank == 1
        assert por_chave["ref-oco"].rank == 2


# ================================================= a máscara ==


class TestAMascara:
    """§12 ao §16 — o que conta como utilizável, e o que para a varredura."""

    def test_ela_segue_a_ordem_do_perfil(self) -> None:
        mascara = availability_mask(
            feature_keys=CINCO_EIXOS,
            values={CINCO_EIXOS[0]: 1.0, CINCO_EIXOS[3]: 2.0},
            availabilities={CINCO_EIXOS[0]: DISPONIVEL, CINCO_EIXOS[3]: DISPONIVEL},
            owner="teste",
        )
        assert mascara == (True, False, False, True, False)
        assert mask_text(mascara) == "10010"
        assert count(mascara) == 2
        assert unselected(CINCO_EIXOS, mascara) == (
            CINCO_EIXOS[1],
            CINCO_EIXOS[2],
            CINCO_EIXOS[4],
        )

    def test_a_intersecao_e_posicional(self) -> None:
        assert shared_mask((True, True, False), (True, False, False)) == (True, False, False)

    def test_mascaras_de_tamanhos_diferentes_param(self) -> None:
        with pytest.raises(ValueError, match="zip"):
            shared_mask((True, True), (True, True, True))

    def test_disponivel_sem_valor_PARA(self) -> None:
        """§15 — falha fechada. Isto é contradição, e não ausência."""
        with pytest.raises(AvailabilityInconsistencyError, match="AVAILABILITY_VALUE"):
            availability_mask(
                feature_keys=(CINCO_EIXOS[0],),
                values={CINCO_EIXOS[0]: None},
                availabilities={CINCO_EIXOS[0]: DISPONIVEL},
                owner="uma linha",
            )

    def test_disponivel_com_NaN_PARA(self) -> None:
        with pytest.raises(AvailabilityInconsistencyError):
            availability_mask(
                feature_keys=(CINCO_EIXOS[0],),
                values={CINCO_EIXOS[0]: math.nan},
                availabilities={CINCO_EIXOS[0]: DISPONIVEL},
                owner="uma linha",
            )

    def test_disponivel_com_infinito_PARA(self) -> None:
        with pytest.raises(AvailabilityInconsistencyError):
            availability_mask(
                feature_keys=(CINCO_EIXOS[0],),
                values={CINCO_EIXOS[0]: math.inf},
                availabilities={CINCO_EIXOS[0]: DISPONIVEL},
                owner="uma linha",
            )

    def test_indisponivel_COM_valor_tambem_PARA(self) -> None:
        """O mais perigoso dos dois: o número está lá, e não deveria ser usado."""
        with pytest.raises(AvailabilityInconsistencyError, match="DEGENERATE"):
            availability_mask(
                feature_keys=(CINCO_EIXOS[0],),
                values={CINCO_EIXOS[0]: 1.0},
                availabilities={CINCO_EIXOS[0]: SEM_ESCALA},
                owner="uma linha",
            )

    def test_indisponivel_sem_valor_e_simplesmente_ausencia(self) -> None:
        assert availability_mask(
            feature_keys=(CINCO_EIXOS[0],),
            values={CINCO_EIXOS[0]: None},
            availabilities={CINCO_EIXOS[0]: SEM_ESCALA},
            owner="uma linha",
        ) == (False,)


# ================================================= a cobertura ==


class TestACoberturaEhContagemAntesDeSerFracao:
    """§54, §55 — as contagens decidem; as frações informam."""

    def test_os_campos_do_contrato(self) -> None:
        aval = CoverageAssessment(
            profile_axis_count=10,
            query_available_count=8,
            candidate_available_count=7,
            shared_count=6,
        )
        assert aval.unshared_count == 4
        assert aval.query_coverage == 0.8
        assert aval.candidate_coverage == 0.7
        assert aval.shared_profile_coverage == 0.6
        assert aval.shared_query_coverage == 0.75
        assert aval.meets_query_floor
        assert aval.meets_shared_floor
        assert not aval.is_complete_case
        assert aval.is_at_shared_floor

    def test_a_cobertura_relativa_a_query_nao_substitui_a_do_perfil(self) -> None:
        """§18, §19 — 100 % do que a query tem pode ser pouco do perfil."""
        aval = CoverageAssessment(
            profile_axis_count=20,
            query_available_count=4,
            candidate_available_count=4,
            shared_count=4,
        )
        assert aval.shared_query_coverage == 1.0
        assert aval.shared_profile_coverage == 0.2
        assert not aval.meets_shared_floor
        assert not aval.meets_query_floor

    def test_query_sem_eixo_nenhum_da_None_e_nao_zero(self) -> None:
        aval = CoverageAssessment(
            profile_axis_count=5,
            query_available_count=0,
            candidate_available_count=0,
            shared_count=0,
        )
        assert aval.shared_query_coverage is None

    def test_a_intersecao_nao_pode_passar_do_menor_lado(self) -> None:
        with pytest.raises(ValidationError, match="interseção"):
            CoverageAssessment(
                profile_axis_count=5,
                query_available_count=2,
                candidate_available_count=5,
                shared_count=3,
            )

    def test_a_impressao_da_cobertura_e_so_contagem(self) -> None:
        aval = CoverageAssessment(
            profile_axis_count=10,
            query_available_count=8,
            candidate_available_count=7,
            shared_count=6,
        )
        assert set(aval.as_canonical()) == {
            "candidate_available_count",
            "profile_axis_count",
            "query_available_count",
            "shared_count",
        }

    def test_o_resumo_e_legivel(self) -> None:
        linhas = coverage_summary(
            CoverageAssessment(
                profile_axis_count=5,
                query_available_count=5,
                candidate_available_count=4,
                shared_count=4,
            )
        )
        assert any("compartilhados" in linha for linha in linhas)


class TestOPerfilPequenoDemais:
    """§24 — a competição inteira é recusada, e o mínimo não cede."""

    def test_perfil_abaixo_do_minimo_recusa_com_tipo_proprio(self) -> None:
        alvo = recuperador(profile=perfil_ciente(eixos=CINCO_EIXOS[:3]))
        with pytest.raises(ProfileInsufficientEvidenceError) as erro:
            alvo.retrieve(
                query=pedido_ciente(),
                snapshot=consulta_ciente(valores=primeiros(3)),
                candidates=[],
                reference_content_fingerprint=REFERENCIA,
            )
        assert erro.value.reason == "PROFILE_INSUFFICIENT_EVIDENCE_AXES"
        assert erro.value.axis_count == 3
        assert erro.value.minimum == 4

    def test_a_causa_e_da_competicao_e_nao_da_query(self) -> None:
        """A query está COMPLETA e a competição continua recusada."""
        alvo = recuperador(profile=perfil_ciente(eixos=CINCO_EIXOS[:2]))
        with pytest.raises(ProfileInsufficientEvidenceError):
            alvo.retrieve(
                query=pedido_ciente(),
                snapshot=consulta_ciente(valores=primeiros(2)),
                candidates=[],
                reference_content_fingerprint=REFERENCIA,
            )


class TestAQuerySemCobertura:
    """§25, §86 — ela é recusada, e nenhuma distância é calculada."""

    def test_query_abaixo_do_piso_recusa_com_tipo_proprio(self) -> None:
        with pytest.raises(QueryInsufficientCoverageError) as erro:
            _recuperar(
                [candidato_ciente(match="ref-a")],
                snapshot=consulta_ciente(valores=primeiros(2)),
            )
        assert erro.value.reason == "QUERY_INSUFFICIENT_COVERAGE"
        assert erro.value.available_axes == 2
        assert len(erro.value.missing_axes) == 3

    def test_nenhum_candidato_e_varrido(self) -> None:
        """§86 — a recusa vem ANTES da varredura, e não depois dela."""
        varridos: list[str] = []

        def _candidatos() -> Iterator[CandidateRow]:
            varridos.append("um")
            yield candidato_ciente(match="ref-a")

        with pytest.raises(QueryInsufficientCoverageError):
            _recuperar(_candidatos(), snapshot=consulta_ciente(valores=primeiros(2)))
        assert varridos == []

    def test_o_perfil_NAO_e_reduzido_a_query(self) -> None:
        """§29 — a query de QUATRO eixos continua medindo cinco.

        ELA É ELEGÍVEL, e o perfil da distância continua com cinco eixos: o
        denominador não encolheu para caber nela.
        """
        resultado = _recuperar(
            [candidato_ciente(match="ref-a")],
            snapshot=consulta_ciente(valores=primeiros(4)),
        )
        assert resultado.axis_count == 5
        assert resultado.query_available_count == 4
        assert resultado.neighbors[0].evidence.coverage.profile_axis_count == 5
        # E O EIXO QUE A QUERY NÃO TEM É PENALIZADO, e não descartado.
        assert resultado.neighbors[0].evidence.missing_penalty_sum == 1.0


# ================================================= a distância ==


class TestAContaEOsSeusContratos:
    def test_o_denominador_e_o_perfil_e_nunca_a_intersecao(self) -> None:
        """§40 — a decisão central, verificada por conta direta."""
        conta = DISTANCIA.evaluate(
            (0.0, 0.0, 0.0, 0.0, None),
            (0.0, 0.0, 0.0, 0.0, None),
            (True, True, True, True, False),
        )
        assert conta.shared_count == 4
        assert conta.observed_squared_sum == 0.0
        assert conta.missing_penalty_sum == 1.0
        # COM DENOMINADOR MÓVEL, ISTO SERIA `0/4 = 0`.
        assert conta.value == 0.2
        assert conta.observed_mse == 0.0

    def test_a_penalidade_e_um_por_eixo(self) -> None:
        assert MISSING_AXIS_PENALTY == 1.0
        assert DISTANCIA.missing_penalty == 1.0
        assert DISTANCIA.missing_penalty_policy == MISSING_AXIS_PENALTY_SQUARED_IQR_V1
        assert DISTANCIA.denominator_policy == FIXED_PROFILE_DENOMINATOR_V1

    def test_a_semantica_de_float_e_a_do_PR_06_1(self) -> None:
        """§51 — a mesma, e o teste existe para que ninguém invente outra."""
        assert DISTANCIA.float_semantics == FLOAT_SEMANTICS_V1
        assert DistanceDefinition(profile=perfil()).float_semantics == FLOAT_SEMANTICS_V1

    def test_nao_finito_no_compartilhado_PARA(self) -> None:
        with pytest.raises(ValidationError, match="finito"):
            DISTANCIA.evaluate(
                (math.nan, 0.0, 0.0, 0.0, 0.0),
                (0.0, 0.0, 0.0, 0.0, 0.0),
                (True,) * 5,
            )

    def test_mascara_de_outro_tamanho_PARA(self) -> None:
        with pytest.raises(ValidationError, match="outro espaço"):
            DISTANCIA.evaluate((0.0,) * 5, (0.0,) * 5, (True,) * 4)

    def test_penalidade_negativa_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="APROXIMAR"):
            AvailabilityAwareDistanceDefinition(profile=perfil_ciente(), missing_penalty=-1.0)

    def test_perfil_de_caso_completo_e_recusado_aqui(self) -> None:
        with pytest.raises(ValidationError, match="CASO COMPLETO"):
            AvailabilityAwareDistanceDefinition(profile=perfil(eixos=CINCO_EIXOS))

    def test_perfil_ciente_e_recusado_no_ORACULO(self) -> None:
        """A guarda do PR-06.1 continua valendo, na direção oposta."""
        with pytest.raises(ValidationError, match=r"PR-06\.2"):
            DistanceDefinition(profile=perfil_ciente())


class TestNaoEhMetrica:
    """§47, §96 ao §100 — o que vale, e o que deliberadamente não vale."""

    def test_nao_negatividade(self) -> None:
        conta = DISTANCIA.evaluate((1.0,) * 5, (-3.0,) * 5, (True,) * 5)
        assert conta.value >= 0

    def test_simetria(self) -> None:
        """§96 — `D(q,c) = D(c,q)` dada a mesma máscara."""
        a = (0.5, 1.5, -2.0, 0.0, 3.0)
        b = (1.0, 0.0, 0.5, -1.0, 2.0)
        mascara = (True, True, False, True, False)
        assert DISTANCIA.evaluate(a, b, mascara).value == DISTANCIA.evaluate(b, a, mascara).value

    def test_auto_dissimilaridade_zero_quando_completo(self) -> None:
        """§98."""
        x = (0.5, 1.5, -2.0, 0.0, 3.0)
        assert DISTANCIA.evaluate(x, x, (True,) * 5).value == 0.0

    def test_auto_dissimilaridade_POSITIVA_quando_incompleto(self) -> None:
        """§97 — a prova mais curta de que isto não é métrica."""
        x = (0.5, 1.5, -2.0, None, None)
        conta = DISTANCIA.evaluate(x, x, (True, True, True, False, False))
        assert conta.value == 0.4
        assert conta.value > 0
        assert DISTANCIA.incomplete_self_dissimilarity(3) == 0.4
        assert DISTANCIA.incomplete_self_dissimilarity(5) == 0.0
        assert not DISTANCIA.is_metric


# ================================================= a evidência ==


class TestAEvidenciaReconstroiONumero:
    """§57, §182, §195 — nenhum vizinho inexplicável."""

    def test_ela_carrega_as_tres_mascaras_e_as_tres_impressoes(self) -> None:
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        prova = resultado.neighbors[0].evidence

        assert prova.query_mask == "11111"
        assert prova.candidate_mask == "11110"
        assert prova.shared_mask == "11110"
        assert prova.resolved_profile_fingerprint == perfil_ciente().fingerprint
        assert prova.distance_definition_fingerprint == distancia_ciente().fingerprint
        assert prova.coverage_policy_fingerprint == DEFAULT_COVERAGE_POLICY.fingerprint

    def test_as_contribuicoes_somam_o_observado(self) -> None:
        valores = {
            CINCO_EIXOS[0]: 1.0,
            CINCO_EIXOS[1]: 2.0,
            CINCO_EIXOS[2]: 0.0,
            CINCO_EIXOS[3]: 0.5,
        }
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=valores)])
        prova = resultado.neighbors[0].evidence

        assert len(prova.contributions) == 4
        assert prova.is_reconstructible
        assert math.fsum(c.squared_contribution for c in prova.contributions) == 5.25
        assert prova.observed_squared_sum == 5.25
        # E O NÚMERO FINAL SAI DAS PARCELAS, sem consultar mais nada.
        assert (prova.observed_squared_sum + prova.missing_penalty_sum) / 5 == prova.dissimilarity

    def test_os_nomes_dos_eixos_saem_separados(self) -> None:
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        prova = resultado.neighbors[0].evidence
        assert prova.shared_features == CINCO_EIXOS[:4]
        assert prova.unshared_features == CINCO_EIXOS[4:]

    def test_ela_NAO_carrega_desfecho(self) -> None:
        """§59 — a lista de ausências é o contrato."""
        prova = _recuperar([candidato_ciente(match="ref-a")]).neighbors[0].evidence
        proibidos = {
            "winner",
            "final_score",
            "next_goal",
            "outcome",
            "label",
            "probability",
            "confidence",
        }
        assert not set(prova.as_canonical()) & proibidos

    def test_a_impressao_e_estavel(self) -> None:
        um = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        outro = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        assert um.neighbors[0].evidence.fingerprint == outro.neighbors[0].evidence.fingerprint

    def test_a_impressao_distingue_mascaras_com_o_mesmo_D(self) -> None:
        """Dois vizinhos com o mesmo número e máscaras diferentes.

        `ref-parcial` tem quatro eixos exatos e um ausente: `D = 1/5`.
        `ref-inteiro` tem os cinco, com `δ² = 1` no último: `D = 1/5`. O número
        é o mesmo e a evidência não é — e a impressão precisa dizer isso.
        """
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-parcial", valores=primeiros(4)),
                candidato_ciente(
                    match="ref-inteiro", valores={**primeiros(4), CINCO_EIXOS[4]: 1.0}
                ),
            ]
        )
        um, outro = resultado.neighbors
        assert um.dissimilarity == outro.dissimilarity == 0.2
        assert um.evidence.fingerprint != outro.evidence.fingerprint

    def test_a_contribuicao_negativa_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="negativa"):
            DistanceContribution(
                feature_key="x",
                query_value=0.0,
                candidate_value=0.0,
                squared_contribution=-1.0,
            )

    def test_o_resumo_e_legivel(self) -> None:
        resultado = _recuperar([candidato_ciente(match="ref-a", valores=primeiros(4))])
        linhas = evidence_summary(resultado.neighbors[0].evidence)
        assert any("dissimilaridade" in linha for linha in linhas)
        assert any("máscara" in linha for linha in linhas)


# ================================================= a ordem ==


class TestATriplaDeOrdenacao:
    """§67, §68, §69, §134 — distância, evidência, chave."""

    def test_a_cobertura_desempata_a_distancia(self) -> None:
        """Mesmo `D`, mais eixos observados → posição melhor.

        O CENÁRIO É CONSTRUÍDO PARA O EMPATE EXATO. `ref-amais` compartilha os
        cinco eixos com `δ = 0` em quatro e `δ² = 1` no quinto: `D = 1/5`.
        `ref-zmenos` compartilha quatro com `δ = 0` e tem um ausente: também
        `D = 1/5`. O primeiro sustenta o número com mais evidência — e ganha
        apesar de a chave dele ser MENOR só por acaso, então o teste usa chaves
        em que a ordem alfabética e a ordem por evidência coincidiriam ao
        contrário se a cobertura não desempatasse.
        """
        mais = {**dict.fromkeys(CINCO_EIXOS, 0.0), CINCO_EIXOS[4]: 1.0}
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-a-menos", valores=primeiros(4)),
                candidato_ciente(match="ref-b-mais", valores=mais),
            ]
        )
        assert [v.dissimilarity for v in resultado.neighbors] == [0.2, 0.2]
        # PELA CHAVE, `ref-a-menos` viria primeiro. PELA EVIDÊNCIA, não vem.
        assert resultado.neighbors[0].key.match_key == "ref-b-mais"
        assert resultado.neighbors[0].shared_count == 5
        assert resultado.neighbors[1].shared_count == 4

    def test_a_chave_desempata_por_ultimo(self) -> None:
        """§134 — mesma distância, mesma cobertura → ordem canônica de chave."""
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-c"),
                candidato_ciente(match="ref-a"),
                candidato_ciente(match="ref-b"),
            ]
        )
        assert [v.key.match_key for v in resultado.neighbors] == ["ref-a", "ref-b", "ref-c"]

    def test_a_cobertura_NAO_lidera(self) -> None:
        """§69 — um candidato completo e distante perde de um parcial e próximo.

        SE A ORDEM FOSSE «cobertura primeiro», `ref-completo` ganharia por ter
        cinco eixos. Ele tem `D = 5·4/5 = 4`; `ref-parcial` tem quatro eixos
        exatos e um ausente, `D = 1/5`.
        """
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-completo", valores=dict.fromkeys(CINCO_EIXOS, 2.0)),
                candidato_ciente(match="ref-parcial", valores=primeiros(4)),
            ]
        )
        assert resultado.neighbors[0].key.match_key == "ref-parcial"
        assert resultado.neighbors[0].dissimilarity == 0.2
        assert resultado.neighbors[1].dissimilarity == 4.0

    def test_a_tripla_do_vizinho_e_a_do_heap(self) -> None:
        """A ordem declarada e a ordem executada são a MESMA definição."""
        resultado = _recuperar(
            [
                candidato_ciente(match="ref-b", valores=primeiros(4)),
                candidato_ciente(match="ref-a", valores=primeiros(5)),
            ]
        )
        chaves = [v.order_key for v in resultado.neighbors]
        assert chaves == sorted(chaves)


# ================================================= os contratos ==


class TestOsCatalogosEOsNomes:
    def test_o_perfil_ciente_tem_o_nome_por_extenso(self) -> None:
        assert AVAILABILITY_AWARE_RETRIEVAL_PROFILE.name == ROBUST_AVAILABILITY_AWARE_EXACT_V1
        assert AVAILABILITY_AWARE_RETRIEVAL_PROFILE.is_availability_aware
        assert not AVAILABILITY_AWARE_RETRIEVAL_PROFILE.is_complete_case
        assert AVAILABILITY_AWARE_RETRIEVAL_PROFILE.is_diagnostic

    def test_o_perfil_do_oraculo_continua_de_caso_completo(self) -> None:
        assert DEFAULT_RETRIEVAL_PROFILE.is_complete_case
        assert not DEFAULT_RETRIEVAL_PROFILE.is_availability_aware
        assert DEFAULT_RETRIEVAL_PROFILE.missing_policy is MissingPolicy.COMPLETE_CASE

    def test_o_metodo_da_distancia_e_fechado_num_membro(self) -> None:
        assert {m.value for m in AvailabilityDistanceMethod} == {
            "AVAILABILITY_AWARE_FIXED_PROFILE_IQR_PENALTY_V1"
        }

    def test_a_politica_de_cobertura_declara_os_cinco_numeros(self) -> None:
        p = DEFAULT_COVERAGE_POLICY
        assert p.name == MINIMUM_EVIDENCE_COVERAGE_V1
        assert p.minimum_profile_axes == 4
        assert p.minimum_query_available_axes == 4
        assert p.minimum_shared_axes == 4
        assert p.query_coverage_floor.text == "3/5"
        assert p.shared_coverage_floor.text == "3/5"

    def test_a_impressao_da_distancia_cobre_o_piso(self) -> None:
        """§48 — dois pisos diferentes são duas definições diferentes."""
        outra = AvailabilityCoveragePolicy(
            name="OUTRO_PISO", shared_coverage_floor=RationalFloor(1, 2)
        )
        assert distancia_ciente().fingerprint != distancia_ciente(coverage_policy=outra).fingerprint

    def test_a_impressao_da_distancia_cobre_a_penalidade(self) -> None:
        dobrada = AvailabilityAwareDistanceDefinition(profile=perfil_ciente(), missing_penalty=2.0)
        assert dobrada.fingerprint != distancia_ciente().fingerprint

    def test_uma_politica_com_piso_maior_que_o_perfil_minimo_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="recusaria tudo"):
            AvailabilityCoveragePolicy(minimum_profile_axes=4, minimum_shared_axes=5)


class TestOsDoisOraculosCoexistem:
    """§73, §74 — o PR-06.1 continua executável, e sobre os mesmos candidatos."""

    def test_o_oraculo_de_caso_completo_ainda_roda(self) -> None:
        from tests.support.retrieval_fixtures import (
            candidato as candidato_cc,
        )
        from tests.support.retrieval_fixtures import (
            consulta as consulta_cc,
        )
        from tests.support.retrieval_fixtures import (
            distancia as distancia_cc,
        )
        from tests.support.retrieval_fixtures import (
            pedido,
        )

        perfil_cc = perfil()
        oraculo = ExactHistoricalRetriever(
            policy=DEFAULT_CANDIDATE_POLICY,
            profile=perfil_cc,
            distance=distancia_cc(perfil_cc),
        )
        resultado = oraculo.retrieve(
            query=pedido(),
            snapshot=consulta_cc(),
            candidates=[candidato_cc(match="ref-a")],
            reference_content_fingerprint=REFERENCIA,
        )
        assert resultado.exhaustive
        assert resultado.returned_k == 1

    def test_os_dois_perfis_resolvem_os_MESMOS_eixos(self) -> None:
        """§10 — a igualdade que torna a comparação uma medição do efeito."""
        assert perfil(eixos=CINCO_EIXOS).feature_keys == perfil_ciente().feature_keys

    def test_e_TEM_impressoes_diferentes(self) -> None:
        """Mesmos eixos, semânticas diferentes: dois números que não se confundem."""
        assert perfil(eixos=CINCO_EIXOS).fingerprint != perfil_ciente().fingerprint
