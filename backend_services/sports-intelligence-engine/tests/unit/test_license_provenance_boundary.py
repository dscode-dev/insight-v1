"""Evidência de identidade não é procedência factual — e a fronteira nos dois lados.

O QUE ESTE ARQUIVO PROTEGE são três afirmações que se contradizem se qualquer
uma for generalizada demais:

    RestrictedIdentityEvidence  ⇏  RestrictedCanonicalFact
        Uma fonte `RESEARCH_ONLY` que apenas escreve `Man City` ajudou a
        RECONHECER o time. Ela não é a autoridade de que a partida aconteceu, e
        deixá-la restringir o núcleo tornaria o §19 inexpressável: não haveria
        cenário em que o núcleo é público e só as odds são restritas.

    RestrictedOnlyFactualEvidence  ⇏  CommercialSafeFact
        Mas quando a restrita é a ÚNICA que afirma que a partida existe, o
        núcleo NÃO vira comercialmente livre só porque os times já tinham id
        canônico. Isso seria lavagem de licença pelo caminho da identidade.

    ResolvedIdentity  ⇏  IgnoreFactualProvenance
        Resolver a identidade não apaga a pergunta «quem afirmou o fato».

E uma quarta, sobre conflito:

    DifferentRawLabels + SameResolvedIdentity  ⇏  CanonicalConflict
        mas horário divergente CONTINUA sendo conflito, porque horário é fato.
"""

from __future__ import annotations

import pytest

from sports_intelligence.domain.build.decisions import BuildOutcome, FamilyExclusionReason
from sports_intelligence.domain.build.policy import (
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
)
from sports_intelligence.domain.fusion.models import FusionRule
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.issues import IssueCode
from sports_intelligence.domain.quality.licensing import (
    LicenseFootprint,
    UsageEligibility,
    UsageScope,
)
from sports_intelligence.domain.quality.policy import DEFAULT_QUALITY_POLICY
from sports_intelligence.domain.quality.runs import MatchQualityRecord
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.domain.sources.semantics import SemanticRole
from sports_intelligence.historical.quality.assessor import HistoricalQualityAssessor
from tests.support.build_fixtures import (
    Cenario,
    cenario,
    kickoff_em_conflito,
    registro_de_odds,
    registro_publico,
    registro_restrito_do_nucleo,
    registro_so_com_grafia,
)

EXECUCAO = "55555555-5555-4555-8555-555555555555"


def _avaliar(cena: Cenario) -> MatchQualityRecord:
    return HistoricalQualityAssessor(policy=DEFAULT_QUALITY_POLICY).assess(
        cena.evidence(), quality_run_id=EXECUCAO
    )


# ============================== a classificação dos papéis ====


class TestPapelERotuloOuFato:
    def test_grafia_de_entidade_e_rotulo(self) -> None:
        """Depois da resolução, o texto não afirma nada sobre o mundo."""
        for papel in (
            SemanticRole.HOME_TEAM_NAME,
            SemanticRole.AWAY_TEAM_NAME,
            SemanticRole.TEAM_NAME,
            SemanticRole.PLAYER_NAME,
            SemanticRole.SEASON_LABEL,
            SemanticRole.COMPETITION_NAME,
            SemanticRole.MATCH_PROVIDER_ID,
        ):
            assert papel.is_identity_label, papel
            assert not papel.is_factual, papel

    def test_horario_e_fato_mesmo_sendo_papel_de_identidade(self) -> None:
        """§12. A regra NÃO é «papel de identidade nunca conta»."""
        assert SemanticRole.KICKOFF.is_identity
        assert not SemanticRole.KICKOFF.is_identity_label
        assert SemanticRole.KICKOFF.is_factual

    def test_observacoes_sao_fato(self) -> None:
        for papel in (
            SemanticRole.HOME_SCORE,
            SemanticRole.AWAY_SCORE,
            SemanticRole.ODDS_HOME,
            SemanticRole.ATTENDANCE,
        ):
            assert papel.is_factual, papel
            assert not papel.is_identity_label, papel


# ============================ cenário A — rótulo restrito ====


class TestCenarioA_GrafiaRestritaNaoContamina:
    """§7. A fonte restrita só empresta o NOME de um time que já é canônico.

    `TeamId(X)` já existe, provado por evidência elegível
    fonte RESEARCH_ONLY escreve `Man City` e mais nada de fato
    → o núcleo da partida NÃO fica restrito
    """

    def _cena(self) -> Cenario:
        return cenario(registro_publico(0), registro_so_com_grafia(0))

    def test_a_grafia_restrita_nao_entra_na_pegada_de_licenca(self) -> None:
        pegada = _avaliar(self._cena()).assessment.usage.footprint
        assert pegada.by_family[CoverageFamily.MATCH] == frozenset({LicenseClass.PUBLIC_DOMAIN})
        assert LicenseClass.RESEARCH_ONLY not in pegada.all_licenses

    def test_o_build_comercial_constroi_o_nucleo(self) -> None:
        decisao = DEFAULT_COMMERCIAL_BUILD_POLICY.decide(_avaliar(self._cena()))
        assert decisao.outcome is BuildOutcome.BUILD
        assert CoverageFamily.MATCH in decisao.included_families
        assert decisao.excluded_by_license == ()

    def test_a_grafia_divergente_nao_e_conflito(self) -> None:
        """§5. `Mandante FC` e `Man City` resolveram para o mesmo `TeamId`, e
        o desacordo textual é exatamente o que a resolução absorve."""
        registro = _avaliar(self._cena())
        assert registro.eligibility is BuildEligibility.ELIGIBLE
        assert registro.families_in_conflict == ()
        assert IssueCode.UNRESOLVED_FUSION_CONFLICT not in {
            p.code for p in registro.assessment.issues
        }


# ==================== cenário B — só a restrita afirma o fato ====


class TestCenarioB_SoRestritaSustentaOFato:
    """§8, §43. A `RESEARCH_ONLY` é a ÚNICA evidência factual da partida.

    Research pode incluir; Commercial NÃO pode tratar o núcleo como elegível.
    """

    def _cena(self) -> Cenario:
        return cenario(registro_restrito_do_nucleo(0))

    def test_o_nucleo_fica_com_procedencia_restrita(self) -> None:
        pegada = _avaliar(self._cena()).assessment.usage.footprint
        assert pegada.by_family[CoverageFamily.MATCH] == frozenset({LicenseClass.RESEARCH_ONLY})
        # E não há suporte independente ELEGÍVEL: a única fonte é a restrita.
        assert (
            pegada.family_verdict(CoverageFamily.MATCH, UsageScope.RESEARCH)
            is UsageEligibility.ELIGIBLE
        )
        assert (
            pegada.family_verdict(CoverageFamily.MATCH, UsageScope.COMMERCIAL)
            is UsageEligibility.INELIGIBLE
        )

    def test_pesquisa_constroi(self) -> None:
        decisao = DEFAULT_RESEARCH_BUILD_POLICY.decide(_avaliar(self._cena()))
        assert decisao.outcome is BuildOutcome.BUILD
        assert CoverageFamily.MATCH in decisao.included_families

    def test_comercial_NAO_transforma_em_elegivel(self) -> None:
        """A lavagem que este teste existe para impedir: os times já têm
        `TeamId` canônico, e isso NÃO torna o fato comercialmente livre."""
        decisao = DEFAULT_COMMERCIAL_BUILD_POLICY.decide(_avaliar(self._cena()))
        assert decisao.outcome is BuildOutcome.SKIP
        assert CoverageFamily.MATCH not in decisao.included_families
        do_nucleo = decisao.decision_for(CoverageFamily.MATCH)
        assert do_nucleo is not None
        assert do_nucleo.reason is FamilyExclusionReason.LICENSE_POLICY
        assert do_nucleo.license_class is LicenseClass.RESEARCH_ONLY

    def test_o_nucleo_nao_e_descartavel_e_por_isso_a_partida_sai(self) -> None:
        """§17. Descartar o núcleo deixaria a partida sem o que a torna uma
        partida — então a política nem oferece essa saída."""
        assert (
            CoverageFamily.MATCH not in DEFAULT_COMMERCIAL_BUILD_POLICY.license_droppable_families
        )


# ================= §42 — confirmação não é derivação ====


class TestSuporteIndependente:
    """Duas fontes dizendo O MESMO não é o mesmo que um desempate entre elas."""

    def _cena_confirmada(self) -> Cenario:
        """Pública e restrita afirmam o MESMO placar e o MESMO horário."""
        return cenario(registro_publico(0), registro_restrito_do_nucleo(0))

    def test_exact_agreement_produz_suporte_independente(self) -> None:
        cena = self._cena_confirmada()
        placar = cena.candidate.field(SemanticRole.HOME_SCORE.value)
        assert placar is not None
        assert placar.rule is FusionRule.EXACT_AGREEMENT

        pegada = _avaliar(cena).assessment.usage.footprint
        assert pegada.by_family[CoverageFamily.MATCH] == frozenset(
            {LicenseClass.PUBLIC_DOMAIN, LicenseClass.RESEARCH_ONLY}
        )
        assert LicenseClass.PUBLIC_DOMAIN in pegada.independent_support[CoverageFamily.MATCH]

    def test_a_presenca_da_restrita_nao_contamina_o_que_a_publica_sustenta(
        self,
    ) -> None:
        """§42. Sem a restrita o valor seria idêntico; ela confirma, não
        deriva — e o corpus comercial não perde a partida por isso."""
        decisao = DEFAULT_COMMERCIAL_BUILD_POLICY.decide(_avaliar(self._cena_confirmada()))
        assert decisao.outcome is BuildOutcome.BUILD
        assert CoverageFamily.MATCH in decisao.included_families

    def test_sem_suporte_independente_declarado_vale_a_regra_restritiva(self) -> None:
        """O default é conservador: uma pegada sem suporte independente decide
        pelo pior, como o PR-04.1 fazia."""
        pegada = LicenseFootprint(
            by_family={
                CoverageFamily.MATCH: frozenset(
                    {LicenseClass.PUBLIC_DOMAIN, LicenseClass.RESEARCH_ONLY}
                )
            }
        )
        assert (
            pegada.family_verdict(CoverageFamily.MATCH, UsageScope.COMMERCIAL)
            is UsageEligibility.INELIGIBLE
        )

    def test_suporte_independente_exige_contribuicao(self) -> None:
        with pytest.raises(Exception, match="não contribuiu"):
            LicenseFootprint(
                by_family={CoverageFamily.MATCH: frozenset({LicenseClass.PUBLIC_DOMAIN})},
                independent_support={CoverageFamily.ODDS: frozenset({LicenseClass.PUBLIC_DOMAIN})},
            )

    def test_desempate_NAO_produz_suporte_independente(self) -> None:
        """§35 do PR-04.1, preservado: quando o valor saiu de uma comparação
        entre fontes, ele foi produzido usando todas."""
        cena = kickoff_em_conflito(0)
        horario = cena.candidate.field(SemanticRole.KICKOFF.value)
        assert horario is not None
        assert horario.rule is FusionRule.CONFLICT_UNRESOLVED
        pegada = _avaliar(cena).assessment.usage.footprint
        assert CoverageFamily.MATCH not in pegada.independent_support or (
            LicenseClass.RESEARCH_ONLY
            not in pegada.independent_support.get(CoverageFamily.MATCH, frozenset())
        )


# ================================== §12, §13 — texto contra fato ====


class TestTextoContraFato:
    def test_horario_incompativel_e_conflito_de_nucleo(self) -> None:
        """§13. Mesma partida resolvida, horários materialmente diferentes:
        a política reage pelas regras que já existem — conflito de núcleo é
        bloqueante."""
        registro = _avaliar(kickoff_em_conflito(0))
        assert IssueCode.UNRESOLVED_FUSION_CONFLICT in {p.code for p in registro.assessment.issues}
        assert registro.eligibility is BuildEligibility.INELIGIBLE

    def test_e_o_build_nao_constroi_a_partida(self) -> None:
        decisao = DEFAULT_RESEARCH_BUILD_POLICY.decide(_avaliar(kickoff_em_conflito(0)))
        assert decisao.outcome is BuildOutcome.SKIP

    def test_a_regra_nao_foi_generalizada_para_todo_papel_de_identidade(self) -> None:
        """A armadilha do §12: excluir rótulo de conflito é certo; excluir
        TODO papel de identidade teria deixado o horário passar."""
        from sports_intelligence.historical.quality.assessor import CORE_ROLES

        assert SemanticRole.KICKOFF in CORE_ROLES
        assert SemanticRole.HOME_TEAM_NAME not in CORE_ROLES


# ============================ §9 — a granularidade preservada ====


class TestGranularidadeDeFamiliaPreservada:
    def test_nucleo_publico_com_odds_restritas(self) -> None:
        cena = cenario(
            registro_publico(0),
            registro_de_odds(0, casa="bet365", cotacao="2.00", linha=1),
            extras=(registro_de_odds(0, casa="pinnacle", cotacao="2.05", linha=2),),
        )
        registro = _avaliar(cena)

        pesquisa = DEFAULT_RESEARCH_BUILD_POLICY.decide(registro)
        comercial = DEFAULT_COMMERCIAL_BUILD_POLICY.decide(registro)

        assert CoverageFamily.MATCH in pesquisa.included_families
        assert CoverageFamily.ODDS in pesquisa.included_families

        assert CoverageFamily.MATCH in comercial.included_families
        assert CoverageFamily.ODDS not in comercial.included_families
        assert comercial.excluded_by_license == (CoverageFamily.ODDS,)
        assert pesquisa.match_id == comercial.match_id
