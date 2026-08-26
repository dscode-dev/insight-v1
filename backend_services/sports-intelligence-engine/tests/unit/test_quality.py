"""Qualidade, cobertura e licença — as três coisas que não podem virar uma.

O QUE ESTES TESTES PROTEGEM é uma separação, e ela é frágil do jeito mais
perigoso: colapsar as três num score único não quebra nada. O código continua
rodando, o relatório continua saindo, e o corpus passa a rejeitar boas fontes
públicas por serem enxutas — ou a aceitar fontes ricas e mal resolvidas.

Metade dos casos aqui verifica que alguma coisa NÃO aconteceu: cobertura zero
que não reprova, licença restrita que não vira defeito de qualidade, ausência
que não vira zero.
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.quality.assessment import (
    BuildEligibility,
    IdentityConfidences,
    MatchQualityAssessment,
    aggregate_quality,
    summarize,
)
from sports_intelligence.domain.quality.coverage import (
    CoverageFamily,
    CoverageReport,
    CoverageState,
    FamilyCoverage,
)
from sports_intelligence.domain.quality.dimensions import QualityDimension, QualityVector
from sports_intelligence.domain.quality.issues import (
    IssueCode,
    QualityIssue,
    Severity,
    sorted_issues,
)
from sports_intelligence.domain.quality.licensing import (
    LicenseFootprint,
    UsageEligibility,
    UsageScope,
    UsageVerdict,
    eligibility_of,
)
from sports_intelligence.domain.quality.policy import (
    DEFAULT_QUALITY_POLICY,
    HistoricalQualityPolicy,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.versions import PolicyVersion
from sports_intelligence.domain.shared.errors import ValidationError
from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.provenance import LicenseClass

POLITICA = DEFAULT_QUALITY_POLICY
PARTIDA = MatchId.derive("teste-qualidade", "city-arsenal")


def _identidades(**valores: float) -> IdentityConfidences:
    padrao = {
        SubjectType.COMPETITION: 1.0,
        SubjectType.SEASON: 1.0,
        SubjectType.TEAM: 1.0,
        SubjectType.MATCH: 1.0,
    }
    padrao.update({SubjectType(k.upper()): v for k, v in valores.items()})
    return IdentityConfidences(by_subject=padrao)


def _licenca_livre() -> UsageVerdict:
    return UsageVerdict.of(
        LicenseFootprint(by_family={CoverageFamily.MATCH: frozenset({LicenseClass.PUBLIC_DOMAIN})})
    )


def _avaliar(
    *,
    quality: QualityVector | None = None,
    coverage: CoverageReport | None = None,
    identity: IdentityConfidences | None = None,
    usage: UsageVerdict | None = None,
    issues: tuple[QualityIssue, ...] = (),
    policy: HistoricalQualityPolicy = POLITICA,
) -> MatchQualityAssessment:
    return MatchQualityAssessment.evaluate(
        match_id=PARTIDA,
        quality=quality or QualityVector.perfect(),
        coverage=coverage or CoverageReport.of(),
        identity=identity or _identidades(),
        usage=usage or _licenca_livre(),
        issues=issues,
        policy=policy,
    )


# ============================================================ dimensões ====


class TestQualityVector:
    def test_o_elo_mais_fraco_governa(self) -> None:
        vetor = QualityVector(
            integrity=1.0,
            consistency=0.4,
            completeness=1.0,
            identity_confidence=0.9,
            temporal_integrity=1.0,
            provenance_quality=1.0,
        )
        eixo, valor = vetor.weakest()
        assert eixo is QualityDimension.CONSISTENCY
        assert valor == pytest.approx(0.4)

    def test_restringir_aos_criticos_ignora_completude(self) -> None:
        """COMPLETUDE NÃO REPROVA, e é a decisão central do §29.

        Ela é cobertura sob outro nome: um registro sem xG está incompleto e
        não está errado. Deixá-la governar o elo mais fraco faria toda fonte
        pública enxuta reprovar.
        """
        vetor = QualityVector(
            integrity=1.0,
            consistency=1.0,
            completeness=0.1,
            identity_confidence=0.95,
            temporal_integrity=1.0,
            provenance_quality=1.0,
        )
        assert vetor.weakest()[0] is QualityDimension.COMPLETENESS
        eixo, valor = vetor.weakest(among=POLITICA.critical_dimensions)
        assert eixo is QualityDimension.IDENTITY_CONFIDENCE
        assert valor == pytest.approx(0.95)

    def test_valor_fora_da_faixa_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="fora de"):
            QualityVector(
                integrity=1.4,
                consistency=1.0,
                completeness=1.0,
                identity_confidence=1.0,
                temporal_integrity=1.0,
                provenance_quality=1.0,
            )

    def test_nao_existe_vetor_perfeito_por_omissao(self) -> None:
        """Nenhum campo tem default: esquecer um eixo é erro, não é 1,0."""
        with pytest.raises(TypeError):
            QualityVector(integrity=1.0)  # type: ignore[call-arg]


# ============================================================= cobertura ===


class TestCoverage:
    def test_nao_declarada_e_diferente_de_zero_por_cento(self) -> None:
        """A distinção que um número sozinho apaga (§13).

        «A fonte não trabalha com eventos» e «a fonte declara eventos e não
        trouxe nenhum» são coisas diferentes: a segunda é defeito.
        """
        ausente = FamilyCoverage.not_declared(CoverageFamily.EVENT)
        vazia = FamilyCoverage.measured(CoverageFamily.EVENT, available=0, expected=380)
        assert ausente.ratio is None
        assert vazia.ratio == pytest.approx(0.0)
        assert ausente.state is CoverageState.NOT_DECLARED
        assert vazia.state is CoverageState.MEASURED

    def test_disponibilidade_sem_denominador_nao_inventa_fracao(self) -> None:
        cobertura = FamilyCoverage.availability(CoverageFamily.ODDS, available=1_200)
        assert cobertura.available_count == 1_200
        assert cobertura.ratio is None

    def test_medido_sem_denominador_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="sem denominador"):
            FamilyCoverage(
                family=CoverageFamily.LINEUP,
                state=CoverageState.MEASURED,
                available_count=10,
            )

    def test_cobertura_acima_de_cem_por_cento_e_recusada(self) -> None:
        """Passar de 100% significa denominador errado, não fonte generosa."""
        with pytest.raises(ValidationError, match="denominador"):
            FamilyCoverage.measured(CoverageFamily.MATCH, available=11, expected=10)

    def test_juntar_escopos_soma_contagens_e_nao_promedia_fracoes(self) -> None:
        """Promediar frações por partida daria metade da cobertura real."""
        uma = CoverageReport.of(
            FamilyCoverage.measured(CoverageFamily.LINEUP, available=1, expected=1)
        )
        noventa_e_nove = CoverageReport.of(
            FamilyCoverage.measured(CoverageFamily.LINEUP, available=0, expected=99)
        )
        junto = uma.merged_with(noventa_e_nove)
        assert junto.ratio_of(CoverageFamily.LINEUP) == pytest.approx(0.01)

    def test_medido_com_disponibilidade_vira_disponibilidade(self) -> None:
        """O denominador que falta de um lado é DESCONHECIDO, não zero."""
        medido = CoverageReport.of(
            FamilyCoverage.measured(CoverageFamily.ODDS, available=5, expected=10)
        )
        solto = CoverageReport.of(FamilyCoverage.availability(CoverageFamily.ODDS, available=7))
        junto = medido.merged_with(solto)
        cobertura = junto.of_family(CoverageFamily.ODDS)
        assert cobertura is not None
        assert cobertura.state is CoverageState.AVAILABILITY_ONLY
        assert cobertura.available_count == 12
        assert cobertura.ratio is None

    def test_tracking_existe_como_nao_declarada(self) -> None:
        """Nomear a ausência distingue «não temos» de «ninguém pensou» (§20)."""
        relatorio = CoverageReport.of(FamilyCoverage.not_declared(CoverageFamily.TRACKING))
        assert CoverageFamily.TRACKING not in relatorio.declared_families


# ================================================== qualidade x cobertura ==


class TestQualidadeNaoEhCobertura:
    def test_cobertura_zero_nao_reprova_partida_integra(self) -> None:
        """§4, §85, §123: o caso que define o PR inteiro.

        Uma fonte pública de futebol tem placar, chutes e cartões, e não tem
        escalação, eventos nem odds. Ela é confiável e enxuta — e um motor
        que a rejeitasse ficaria sem as melhores fontes históricas que existem.
        """
        avaliacao = _avaliar(
            coverage=CoverageReport.of(
                FamilyCoverage.measured(CoverageFamily.MATCH, available=380, expected=380),
                FamilyCoverage.not_declared(CoverageFamily.LINEUP),
                FamilyCoverage.not_declared(CoverageFamily.EVENT),
                FamilyCoverage.not_declared(CoverageFamily.ODDS),
            )
        )
        assert avaliacao.eligibility is BuildEligibility.ELIGIBLE
        assert avaliacao.reason is None

    def test_riqueza_alta_com_identidade_fraca_nao_passa(self) -> None:
        """§124, o outro lado: cobertura completa não compra elegibilidade.

        Escalação, eventos, coordenadas e odds — e um jogador resolvido a
        0,50. As duas dimensões não podem colapsar no mesmo significado.
        """
        avaliacao = _avaliar(
            coverage=CoverageReport.of(
                FamilyCoverage.measured(CoverageFamily.MATCH, available=380, expected=380),
                FamilyCoverage.measured(CoverageFamily.LINEUP, available=380, expected=380),
                FamilyCoverage.measured(CoverageFamily.EVENT, available=500, expected=500),
                FamilyCoverage.measured(CoverageFamily.ODDS, available=380, expected=380),
                FamilyCoverage.measured(CoverageFamily.SPATIAL, available=500, expected=500),
            ),
            identity=IdentityConfidences(
                by_subject={
                    SubjectType.COMPETITION: 1.0,
                    SubjectType.SEASON: 1.0,
                    SubjectType.TEAM: 1.0,
                    SubjectType.MATCH: 1.0,
                    SubjectType.PLAYER: 0.50,
                }
            ),
        )
        assert avaliacao.eligibility is BuildEligibility.REVIEW_REQUIRED
        assert "PLAYER" in (avaliacao.reason or "")

    def test_confianca_de_identidade_nao_e_media(self) -> None:
        """§9: a competição em 1,0 não pode mascarar o jogador em 0,5.

        A média dos cinco daria 0,9, que passa em quase qualquer piso — e o
        jogador errado é o que contamina influência, elenco e grafo tático de
        forma que ninguém detecta depois.
        """
        identidades = IdentityConfidences(
            by_subject={
                SubjectType.COMPETITION: 1.0,
                SubjectType.SEASON: 1.0,
                SubjectType.TEAM: 1.0,
                SubjectType.MATCH: 1.0,
                SubjectType.PLAYER: 0.50,
            }
        )
        assert sum(identidades.by_subject.values()) / 5 == pytest.approx(0.9)
        falta = identidades.weakest_against(POLITICA)
        assert falta is not None
        assert falta[0] is SubjectType.PLAYER


# =============================================================== licença ===


class TestLicenca:
    @pytest.mark.parametrize(
        ("licenca", "pesquisa", "comercial"),
        [
            (LicenseClass.PUBLIC_DOMAIN, UsageEligibility.ELIGIBLE, UsageEligibility.ELIGIBLE),
            (
                LicenseClass.COMMERCIAL_ALLOWED,
                UsageEligibility.ELIGIBLE,
                UsageEligibility.ELIGIBLE,
            ),
            (
                LicenseClass.ATTRIBUTION_REQUIRED,
                UsageEligibility.ELIGIBLE,
                UsageEligibility.ELIGIBLE,
            ),
            (
                LicenseClass.RESEARCH_ONLY,
                UsageEligibility.ELIGIBLE,
                UsageEligibility.INELIGIBLE,
            ),
            (
                LicenseClass.UNKNOWN,
                UsageEligibility.REVIEW_REQUIRED,
                UsageEligibility.REVIEW_REQUIRED,
            ),
        ],
    )
    def test_as_cinco_classes(
        self,
        licenca: LicenseClass,
        pesquisa: UsageEligibility,
        comercial: UsageEligibility,
    ) -> None:
        assert eligibility_of(licenca, UsageScope.RESEARCH) is pesquisa
        assert eligibility_of(licenca, UsageScope.COMMERCIAL) is comercial

    def test_desconhecida_nao_vira_permissiva(self) -> None:
        """§34: supor permissividade é o erro que custa caro depois."""
        assert (
            eligibility_of(LicenseClass.UNKNOWN, UsageScope.COMMERCIAL)
            is not UsageEligibility.ELIGIBLE
        )

    def test_sem_licenca_nenhuma_vai_para_revisao(self) -> None:
        """Vazio não é permissivo: é origem desconhecida."""
        vazio = UsageVerdict.of(LicenseFootprint())
        assert vazio.commercial is UsageEligibility.REVIEW_REQUIRED

    def test_a_mais_restritiva_governa_o_conjunto(self) -> None:
        """§35: não é a fonte que venceu mais campos."""
        pegada = LicenseFootprint(
            by_family={
                CoverageFamily.MATCH: frozenset({LicenseClass.PUBLIC_DOMAIN}),
                CoverageFamily.LINEUP: frozenset({LicenseClass.ATTRIBUTION_REQUIRED}),
                CoverageFamily.ODDS: frozenset({LicenseClass.RESEARCH_ONLY}),
            }
        )
        veredito = UsageVerdict.of(pegada)
        assert veredito.research is UsageEligibility.ELIGIBLE
        assert veredito.commercial is UsageEligibility.INELIGIBLE
        assert veredito.commercial_blockers == (CoverageFamily.ODDS,)

    def test_excluir_a_familia_restrita_libera_o_comercial(self) -> None:
        """§36: a contaminação não é irreversível quando dá para excluir.

        Se a fonte `RESEARCH_ONLY` só trouxe odds e o build comercial as
        descarta, o núcleo da partida não foi produzido com ela.
        """
        pegada = LicenseFootprint(
            by_family={
                CoverageFamily.MATCH: frozenset({LicenseClass.PUBLIC_DOMAIN}),
                CoverageFamily.ODDS: frozenset({LicenseClass.RESEARCH_ONLY}),
            }
        )
        com_odds = UsageVerdict.of(pegada)
        sem_odds = UsageVerdict.of(pegada, commercial_exclusions=POLITICA.commercially_droppable)
        assert com_odds.commercial is UsageEligibility.INELIGIBLE
        assert sem_odds.commercial is UsageEligibility.ELIGIBLE
        assert not com_odds.allows(UsageScope.COMMERCIAL)
        assert sem_odds.allows(UsageScope.COMMERCIAL)

    def test_licenca_restrita_nao_e_defeito_de_qualidade(self) -> None:
        """§30: uma fonte impecável sob `RESEARCH_ONLY` continua impecável.

        `LICENSE_RESTRICTED` é `INFO` na política, e o problema não tem
        dimensão de qualidade nenhuma — é o tipo dizendo que não é qualidade.
        """
        problema = QualityIssue.of(IssueCode.LICENSE_RESTRICTED, subject=str(PARTIDA))
        assert problema.dimension is None
        assert not problema.is_quality
        assert POLITICA.severity_of(IssueCode.LICENSE_RESTRICTED) is Severity.INFO

        avaliacao = _avaliar(
            usage=UsageVerdict.of(
                LicenseFootprint(
                    by_family={CoverageFamily.MATCH: frozenset({LicenseClass.RESEARCH_ONLY})}
                )
            ),
            issues=(problema,),
        )
        # Elegível para o corpus, e SÓ para pesquisa. As duas afirmações são
        # verdadeiras ao mesmo tempo.
        assert avaliacao.eligibility is BuildEligibility.ELIGIBLE
        assert avaliacao.allows(UsageScope.RESEARCH)
        assert not avaliacao.allows(UsageScope.COMMERCIAL)


# ============================================================= problemas ===


class TestProblemas:
    def test_o_validador_nao_carimba_severidade(self) -> None:
        """§22: o problema diz O QUE achou; a política diz QUANTO pesa."""
        problema = QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="ref")
        assert not hasattr(problema, "severity")
        assert POLITICA.severity_of(IssueCode.BROKEN_LINEAGE) is Severity.BLOCKING

    def test_codigo_desconhecido_pela_politica_nao_bloqueia(self) -> None:
        """Um código sem severidade declarada é `WARNING`, nunca bloqueante.

        Default brando de propósito: um código novo não pode passar a
        derrubar o corpus por acidente de omissão.
        """
        magra = HistoricalQualityPolicy(
            version=PolicyVersion(major=9, minor=9),
            critical_dimensions=frozenset({QualityDimension.INTEGRITY}),
        )
        assert magra.severity_of(IssueCode.SAME_TEAM_BOTH_SIDES) is Severity.WARNING
        assert not magra.severity_of(IssueCode.SAME_TEAM_BOTH_SIDES).blocks

    def test_ordem_dos_problemas_e_estavel(self) -> None:
        """§102: a lista entra na impressão, então a ordem é parte do contrato."""
        um = QualityIssue.of(IssueCode.MISSING_RESULT, subject="b")
        dois = QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="a")
        tres = QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="z")
        assert sorted_issues((um, tres, dois)) == (dois, tres, um)

    def test_problema_sem_sujeito_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="sem sujeito"):
            QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="   ")

    def test_contexto_gigante_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="caracteres"):
            QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="x", detalhe="a" * 500)


# =============================================================== política ==


class TestPolitica:
    def test_politica_sem_eixo_critico_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="eixo crítico"):
            HistoricalQualityPolicy(version=PolicyVersion(major=1, minor=0))

    def test_piso_em_eixo_nao_critico_e_recusado(self) -> None:
        """Um piso que não reprova é um número que engana quem lê."""
        with pytest.raises(ValidationError, match="não é crítica"):
            HistoricalQualityPolicy(
                version=PolicyVersion(major=1, minor=0),
                critical_dimensions=frozenset({QualityDimension.INTEGRITY}),
                minimums={QualityDimension.COMPLETENESS: 0.8},
            )

    def test_a_forma_canonica_e_deterministica(self) -> None:
        """Ela entra na impressão do manifesto: duas leituras, mesma saída."""
        assert POLITICA.as_canonical() == POLITICA.as_canonical()
        assert POLITICA.as_canonical()["version"] == str(POLITICA.version)


# ============================================================== avaliação ==


class TestAvaliacao:
    def test_registro_impecavel_entra(self) -> None:
        assert _avaliar().eligibility is BuildEligibility.ELIGIBLE

    def test_bloqueante_impede(self) -> None:
        avaliacao = _avaliar(
            issues=(QualityIssue.of(IssueCode.SAME_TEAM_BOTH_SIDES, subject=str(PARTIDA)),)
        )
        assert avaliacao.eligibility is BuildEligibility.INELIGIBLE
        assert not avaliacao.eligibility.enters_build

    def test_linhagem_quebrada_bloqueia(self) -> None:
        """O corpus se justifica por ser rastreável (§11, §115)."""
        avaliacao = _avaliar(issues=(QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="campo"),))
        assert avaliacao.eligibility is BuildEligibility.INELIGIBLE

    def test_conflito_de_fusao_no_nucleo_bloqueia(self) -> None:
        """§132: o conflito preservado pelo PR-03 vira blocker aqui."""
        avaliacao = _avaliar(
            issues=(QualityIssue.of(IssueCode.UNRESOLVED_FUSION_CONFLICT, subject="HOME_SCORE"),)
        )
        assert avaliacao.eligibility is BuildEligibility.INELIGIBLE

    def test_erro_grave_vai_para_revisao_e_nao_entra_sozinho(self) -> None:
        """§27, §38: `REVIEW_REQUIRED` é o meio-termo que um booleano perde."""
        avaliacao = _avaliar(
            issues=(QualityIssue.of(IssueCode.TEMPORAL_INCONSISTENCY, subject=str(PARTIDA)),)
        )
        assert avaliacao.eligibility is BuildEligibility.REVIEW_REQUIRED
        assert not avaliacao.eligibility.enters_build

    def test_resultado_ausente_nao_bloqueia(self) -> None:
        """§29, §55: falta de placar reduz o que dá para fazer, não invalida."""
        avaliacao = _avaliar(
            issues=(QualityIssue.of(IssueCode.MISSING_RESULT, subject=str(PARTIDA)),)
        )
        assert avaliacao.eligibility is BuildEligibility.ELIGIBLE

    def test_piso_de_eixo_critico_reprova(self) -> None:
        avaliacao = _avaliar(
            quality=QualityVector(
                integrity=1.0,
                consistency=1.0,
                completeness=1.0,
                identity_confidence=1.0,
                temporal_integrity=1.0,
                provenance_quality=0.5,
            )
        )
        assert avaliacao.eligibility is BuildEligibility.INELIGIBLE
        assert "PROVENANCE_QUALITY" in (avaliacao.reason or "")

    def test_a_avaliacao_e_deterministica(self) -> None:
        """§102: mesma entrada e política → mesmo veredito e mesma ordem."""
        problemas = (
            QualityIssue.of(IssueCode.MISSING_RESULT, subject="b"),
            QualityIssue.of(IssueCode.EVENT_OUT_OF_ORDER, subject="a"),
        )
        uma = _avaliar(issues=problemas)
        outra = _avaliar(issues=tuple(reversed(problemas)))
        assert uma.as_canonical() == outra.as_canonical()

    def test_o_agregado_e_o_pior_caso_e_nao_a_media(self) -> None:
        """§83: cem partidas ruins não podem sumir no terceiro decimal."""
        boa = _avaliar()
        ruim = _avaliar(
            quality=QualityVector(
                integrity=0.2,
                consistency=1.0,
                completeness=1.0,
                identity_confidence=1.0,
                temporal_integrity=1.0,
                provenance_quality=1.0,
            )
        )
        agregado = aggregate_quality((boa,) * 99 + (ruim,))
        assert agregado is not None
        assert agregado.integrity == pytest.approx(0.2)

    def test_corpus_vazio_nao_e_corpus_impecavel(self) -> None:
        assert aggregate_quality(()) is None

    def test_resumo_conta_os_tres_vereditos(self) -> None:
        contagem = summarize(
            (
                _avaliar(),
                _avaliar(issues=(QualityIssue.of(IssueCode.BROKEN_LINEAGE, subject="x"),)),
            )
        )
        assert contagem[BuildEligibility.ELIGIBLE] == 1
        assert contagem[BuildEligibility.INELIGIBLE] == 1
        assert contagem[BuildEligibility.REVIEW_REQUIRED] == 0
