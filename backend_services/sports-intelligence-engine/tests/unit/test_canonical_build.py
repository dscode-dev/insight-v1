"""A construção canônica: política, construtores tipados e primeiro write.

O QUE ESTES TESTES PROTEGEM é a passagem

    evidência fundida → decisão de qualidade → fato canônico

sem que nenhuma das três coisas proibidas aconteça pelo caminho: o construtor
reavaliar qualidade, a ausência virar zero, e o fato existente ser
sobrescrito.

Boa parte dos casos verifica que algo NÃO aconteceu — o placar ausente que não
vira `0-0`, a família restrita que não derruba a partida, o `Match` que
continua sem resultado, o segundo build que não duplica nada.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal

import pytest

from sports_intelligence.application.use_cases.canonical_build import (
    BuildCandidateBatch,
    GetCanonicalBuildRun,
    GetMatchLineage,
    RunCanonicalBuild,
)
from sports_intelligence.application.use_cases.quality import (
    RunHistoricalQualityAssessment,
)
from sports_intelligence.domain.build.decisions import (
    BUILDABLE_FAMILIES,
    BuildDecision,
    BuildOutcome,
    CanonicalFactType,
    FamilyDecision,
    FamilyExclusionReason,
    FamilyOutcome,
)
from sports_intelligence.domain.build.facts import (
    LineupDraft,
    LineupDraftEntry,
    ScoreFacts,
)
from sports_intelligence.domain.build.policy import (
    CURRENT_BUILD_POLICY_VERSION,
    DEFAULT_COMMERCIAL_BUILD_POLICY,
    DEFAULT_RESEARCH_BUILD_POLICY,
    CanonicalBuildPolicy,
    OptionalConflictHandling,
    ReviewHandling,
)
from sports_intelligence.domain.build.runs import (
    BuildCounts,
    BuildRecordStatus,
    CanonicalBuildRecord,
    CanonicalBuildRun,
    MatchWriteOutcome,
    assert_not_a_published_corpus,
)
from sports_intelligence.domain.matches.lineup import LineupStatus
from sports_intelligence.domain.matches.models import Match
from sports_intelligence.domain.matches.result import MatchResult
from sports_intelligence.domain.quality.coverage import CoverageFamily
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.quality.policy import DEFAULT_QUALITY_POLICY
from sports_intelligence.domain.quality.runs import (
    MatchQualityRecord,
    QualityRun,
    QualityRunInput,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    InvariantViolationError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.fingerprint import policy_fingerprint
from sports_intelligence.domain.shared.identity import PlayerId
from sports_intelligence.historical.build.assembly import (
    CanonicalAssembler,
    MatchBuildInputs,
    records_of,
)
from sports_intelligence.historical.build.builders import (
    BUILT_LIFECYCLE,
    CanonicalLineupBuilder,
    CanonicalMatchBuilder,
    CanonicalOddsBuilder,
    CanonicalResultBuilder,
)
from sports_intelligence.historical.build.translation import (
    odds_observations_of,
    read_score_facts,
)
from sports_intelligence.historical.quality.assessor import HistoricalQualityAssessor
from sports_intelligence.ports.clock import FrozenClock
from tests.support.build_doubles import (
    FakeAudit,
    FakeCanonicalBuildRecordRepository,
    FakeCanonicalBuildRunRepository,
    FakeCanonicalIdentityReader,
    FakeCanonicalRegistryWriter,
    FakeFusionRunRepository,
    FakeQualityAssessmentRepository,
    FakeQualityRunRepository,
)
from tests.support.build_fixtures import (
    AGORA,
    CASA,
    CONFIANCAS_BOAS,
    Cenario,
    cenario_publico_com_odds,
    cenarios,
    fusion_run_concluida,
    identity_facts,
    match_id,
    placar_em_conflito,
    sem_odds,
    sem_placar,
    um_lote,
)

ATOR = Actor.service("historical-canonical-builder")
AVALIADOR = HistoricalQualityAssessor(policy=DEFAULT_QUALITY_POLICY)


#: A execução de qualidade sob a qual os vereditos deste arquivo nascem.
EXECUCAO_DE_QUALIDADE = "11111111-1111-4111-8111-111111111111"


def _veredito(
    cena: Cenario, *, confidences: Mapping[SubjectType, float] | None = None
) -> MatchQualityRecord:
    return AVALIADOR.assess(
        cena.evidence(confidences=confidences), quality_run_id=EXECUCAO_DE_QUALIDADE
    )


def _decidir(
    cena: Cenario,
    policy: CanonicalBuildPolicy = DEFAULT_RESEARCH_BUILD_POLICY,
    *,
    confidences: Mapping[SubjectType, float] | None = None,
) -> BuildDecision:
    return policy.decide(_veredito(cena, confidences=confidences))


# ================================================ a política de build ====


class TestCanonicalBuildPolicy:
    def test_e_versionada_e_tem_escopo(self) -> None:
        assert DEFAULT_RESEARCH_BUILD_POLICY.version == CURRENT_BUILD_POLICY_VERSION
        assert DEFAULT_RESEARCH_BUILD_POLICY.scope is UsageScope.RESEARCH
        assert DEFAULT_COMMERCIAL_BUILD_POLICY.scope is UsageScope.COMMERCIAL

    def test_recusa_politica_sem_familia_obrigatoria(self) -> None:
        """Ela construiria uma partida sem nenhum dado."""
        with pytest.raises(ValidationError, match="sem família obrigatória"):
            CanonicalBuildPolicy(version=CURRENT_BUILD_POLICY_VERSION, scope=UsageScope.RESEARCH)

    def test_recusa_exigir_familia_que_o_contrato_nao_carrega(self) -> None:
        """§28, §92. Um build que exigisse `EVENT` reprovaria todo o corpus
        por um limite NOSSO, e o relatório culparia a fonte."""
        with pytest.raises(ValidationError, match="não carrega"):
            CanonicalBuildPolicy(
                version=CURRENT_BUILD_POLICY_VERSION,
                scope=UsageScope.RESEARCH,
                required_families=frozenset({CoverageFamily.EVENT}),
            )

    def test_recusa_familia_obrigatoria_e_descartavel(self) -> None:
        with pytest.raises(ValidationError, match="obrigatória marcada"):
            CanonicalBuildPolicy(
                version=CURRENT_BUILD_POLICY_VERSION,
                scope=UsageScope.COMMERCIAL,
                required_families=frozenset({CoverageFamily.MATCH}),
                license_droppable_families=frozenset({CoverageFamily.MATCH}),
            )

    def test_a_lista_de_descartaveis_vem_da_politica_de_qualidade(self) -> None:
        """§5. Duas listas divergiriam no primeiro ajuste, e a divergência
        significaria publicar comercialmente uma família restrita."""
        assert (
            DEFAULT_COMMERCIAL_BUILD_POLICY.license_droppable_families
            is DEFAULT_QUALITY_POLICY.commercially_droppable
        )

    def test_elegivel_constroi(self) -> None:
        """§85."""
        decisao = _decidir(cenario_publico_com_odds())
        assert decisao.outcome is BuildOutcome.BUILD
        assert decisao.includes(CoverageFamily.MATCH)

    def test_inelegivel_e_pulada(self) -> None:
        decisao = _decidir(placar_em_conflito())
        assert decisao.outcome is BuildOutcome.SKIP
        assert decisao.included_families == ()
        assert "INELIGIBLE" in (decisao.reason or "")

    def test_review_required_nao_constroi_automaticamente(self) -> None:
        """§85. Ele fica FORA do build automático até alguém olhar."""
        decisao = _decidir(
            cenario_publico_com_odds(),
            confidences={**CONFIANCAS_BOAS, SubjectType.TEAM: 0.91},
        )
        assert decisao.outcome is BuildOutcome.REVIEW_REQUIRED
        assert decisao.included_families == ()

    def test_review_pode_construir_so_o_nucleo_quando_a_politica_declara(self) -> None:
        """A outra saída do §17, e ela é DECLARADA — nunca o default."""
        permissiva = replace(
            DEFAULT_RESEARCH_BUILD_POLICY,
            on_review_required=ReviewHandling.BUILD_CORE_ONLY,
        )
        decisao = _decidir(
            cenario_publico_com_odds(),
            policy=permissiva,
            confidences={**CONFIANCAS_BOAS, SubjectType.TEAM: 0.91},
        )
        assert decisao.outcome is BuildOutcome.BUILD
        assert decisao.included_families == (CoverageFamily.MATCH,)
        odds = decisao.decision_for(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.reason is FamilyExclusionReason.ASSESSMENT_REVIEW

    def test_familia_ausente_nao_derruba_a_partida(self) -> None:
        """§14, §39. Odds ausentes reduzem o que se pode fazer com a partida
        e não a tornam falsa."""
        decisao = _decidir(sem_odds())
        assert decisao.outcome is BuildOutcome.BUILD
        odds = decisao.decision_for(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.reason is FamilyExclusionReason.NOT_AVAILABLE

    def test_conflito_de_familia_opcional_nao_derruba_a_partida(self) -> None:
        """§46, a regra inteira: a família some, a partida fica.

        O CONFLITO É INJETADO NO VEREDITO, e não produzido pelo cenário — o
        contrato fundido da V1 não tem nenhuma família OPCIONAL cujo valor
        possa entrar em conflito escalar: odds são observações e nunca
        conflitam, e escalação não é carregada por papel nenhum. A regra
        existe e é testada; a entrada que a dispara ainda não existe, e isso
        está declarado em vez de simulado com dado inventado.
        """
        veredito = replace(
            _veredito(cenario_publico_com_odds()),
            families_in_conflict=(CoverageFamily.ODDS,),
        )
        decisao = DEFAULT_RESEARCH_BUILD_POLICY.decide(veredito)
        assert decisao.outcome is BuildOutcome.BUILD
        odds = decisao.decision_for(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.reason is FamilyExclusionReason.UNRESOLVED_CONFLICT
        assert CoverageFamily.MATCH in decisao.included_families

    def test_conflito_opcional_pode_ir_para_revisao_quando_declarado(self) -> None:
        revisora = replace(
            DEFAULT_RESEARCH_BUILD_POLICY,
            on_optional_conflict=OptionalConflictHandling.REVIEW_FAMILY,
        )
        veredito = replace(
            _veredito(cenario_publico_com_odds()),
            families_in_conflict=(CoverageFamily.ODDS,),
        )
        decisao = revisora.decide(veredito)
        odds = decisao.decision_for(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.outcome is FamilyOutcome.REVIEW_REQUIRED
        assert decisao.outcome is BuildOutcome.BUILD

    def test_conflito_em_familia_OBRIGATORIA_derruba_a_partida(self) -> None:
        """§45. Escolher uma das fontes seria inventar o fato."""
        veredito = replace(
            _veredito(cenario_publico_com_odds()),
            families_in_conflict=(CoverageFamily.MATCH,),
        )
        decisao = DEFAULT_RESEARCH_BUILD_POLICY.decide(veredito)
        assert decisao.outcome is BuildOutcome.SKIP
        assert "divergem sem resolução" in (decisao.reason or "")

    def test_sem_placar_a_politica_que_exige_resultado_pula(self) -> None:
        """§33. Quem decide se a partida pode existir sem resultado é a
        política — e a que exige resultado não constrói buracos."""
        assert DEFAULT_RESEARCH_BUILD_POLICY.require_result is True
        decisao = _decidir(sem_placar())
        assert decisao.outcome is BuildOutcome.SKIP
        assert "placar" in (decisao.reason or "")

    def test_sem_placar_a_politica_de_calendario_constroi(self) -> None:
        calendario = replace(DEFAULT_RESEARCH_BUILD_POLICY, require_result=False)
        decisao = _decidir(sem_placar(), policy=calendario)
        assert decisao.outcome is BuildOutcome.BUILD
        assert decisao.includes(CoverageFamily.MATCH)

    def test_familia_nao_declarada_nao_gera_linha_de_decisao(self) -> None:
        """A fonte nunca prometeu eventos, então não há o que explicar sobre
        eles nesta partida — o limite é do CONTRATO e está declarado em
        `BUILDABLE_FAMILIES`, não numa linha por partida (§28, §92)."""
        decisao = _decidir(cenario_publico_com_odds())
        assert decisao.decision_for(CoverageFamily.EVENT) is None

    def test_familia_DECLARADA_e_fora_do_escopo_aparece_com_motivo(self) -> None:
        """§20. Uma fonte que TROUXE eventos precisa ver «excluída, fora do
        escopo desta fase» — e não o silêncio, indistinguível de esquecimento.
        """
        from sports_intelligence.domain.quality.coverage import (
            CoverageReport,
            FamilyCoverage,
        )

        base = _veredito(cenario_publico_com_odds())
        com_eventos = replace(
            base,
            assessment=replace(
                base.assessment,
                coverage=CoverageReport.of(
                    *base.assessment.coverage.families[:1],
                    FamilyCoverage.availability(CoverageFamily.EVENT, available=42),
                ),
            ),
        )
        decisao = DEFAULT_RESEARCH_BUILD_POLICY.decide(com_eventos)
        evento = decisao.decision_for(CoverageFamily.EVENT)
        assert evento is not None
        assert evento.reason is FamilyExclusionReason.OUT_OF_BUILD_SCOPE

    def test_o_limite_de_familias_construiveis_esta_declarado(self) -> None:
        assert (
            frozenset({CoverageFamily.MATCH, CoverageFamily.LINEUP, CoverageFamily.ODDS})
            == BUILDABLE_FAMILIES
        )
        assert CoverageFamily.EVENT not in BUILDABLE_FAMILIES


# ======================================= pesquisa contra comércio ====


class TestPesquisaContraComercio:
    """§19, §86, §103 — o cenário que separa os dois corpus."""

    def test_a_pesquisa_inclui_as_odds_restritas(self) -> None:
        decisao = _decidir(cenario_publico_com_odds(), DEFAULT_RESEARCH_BUILD_POLICY)
        assert decisao.outcome is BuildOutcome.BUILD
        assert CoverageFamily.MATCH in decisao.included_families
        assert CoverageFamily.ODDS in decisao.included_families
        assert decisao.excluded_by_license == ()

    def test_o_comercial_exclui_as_odds_por_licenca(self) -> None:
        decisao = _decidir(cenario_publico_com_odds(), DEFAULT_COMMERCIAL_BUILD_POLICY)
        assert decisao.outcome is BuildOutcome.BUILD
        assert CoverageFamily.MATCH in decisao.included_families
        assert CoverageFamily.ODDS not in decisao.included_families
        assert decisao.excluded_by_license == (CoverageFamily.ODDS,)

    def test_a_exclusao_diz_QUAL_licença_a_causou(self) -> None:
        """§20. «ODDS excluída» não responde nada; «por LICENSE_POLICY,
        RESEARCH_ONLY, num build COMMERCIAL» responde tudo."""
        from sports_intelligence.domain.shared.provenance import LicenseClass

        decisao = _decidir(cenario_publico_com_odds(), DEFAULT_COMMERCIAL_BUILD_POLICY)
        odds = decisao.decision_for(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.reason is FamilyExclusionReason.LICENSE_POLICY
        assert odds.license_class is LicenseClass.RESEARCH_ONLY

    def test_a_identidade_da_partida_e_a_mesma_nos_dois(self) -> None:
        """§19. O que muda é o conjunto de famílias, nunca a partida."""
        cena = cenario_publico_com_odds()
        pesquisa = _decidir(cena, DEFAULT_RESEARCH_BUILD_POLICY)
        comercial = _decidir(cena, DEFAULT_COMMERCIAL_BUILD_POLICY)
        assert pesquisa.match_id == comercial.match_id
        assert pesquisa.scope is not comercial.scope

    def test_familia_restrita_e_NAO_descartavel_derruba_a_partida(self) -> None:
        """A exclusão é uma PERMISSÃO declarada (§17). Sem ela, usar o dado
        seria publicar sem direito, e descartá-lo seria contornar a restrição
        por conta própria — então a partida não entra."""
        sem_permissao = replace(
            DEFAULT_COMMERCIAL_BUILD_POLICY, license_droppable_families=frozenset()
        )
        decisao = _decidir(cenario_publico_com_odds(), sem_permissao)
        assert decisao.outcome is BuildOutcome.SKIP
        assert "não autoriza descartá-la" in (decisao.reason or "")


# ================================================ decisões e famílias ====


class TestFamilyDecision:
    def test_exclusao_sem_motivo_e_recusada(self) -> None:
        """§20. Uma família que some sem explicação é indistinguível de uma
        que nunca existiu."""
        with pytest.raises(ValidationError, match="sem motivo"):
            FamilyDecision(family=CoverageFamily.ODDS, outcome=FamilyOutcome.EXCLUDED)

    def test_exclusao_por_licenca_sem_licenca_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="sem dizer QUAL"):
            FamilyDecision.excluded(CoverageFamily.ODDS, FamilyExclusionReason.LICENSE_POLICY)

    def test_incluida_com_motivo_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="incluída com motivo"):
            FamilyDecision(
                family=CoverageFamily.MATCH,
                outcome=FamilyOutcome.INCLUDED,
                reason=FamilyExclusionReason.NOT_AVAILABLE,
            )

    def test_partida_recusada_nao_pode_ter_familia_incluida(self) -> None:
        with pytest.raises(ValidationError, match="família\\(s\\) incluída"):
            BuildDecision.of(
                match_id=match_id(),
                outcome=BuildOutcome.SKIP,
                scope=UsageScope.RESEARCH,
                build_policy_version=CURRENT_BUILD_POLICY_VERSION,
                families=(FamilyDecision.included(CoverageFamily.MATCH),),
                reason="qualquer",
            )

    def test_familia_nao_decidida_nao_entra_por_omissao(self) -> None:
        decisao = BuildDecision.of(
            match_id=match_id(),
            outcome=BuildOutcome.BUILD,
            scope=UsageScope.RESEARCH,
            build_policy_version=CURRENT_BUILD_POLICY_VERSION,
            families=(FamilyDecision.included(CoverageFamily.MATCH),),
        )
        assert decisao.includes(CoverageFamily.MATCH)
        assert not decisao.includes(CoverageFamily.ODDS)


# ==================================================== os construtores ====


def _decisao_completa() -> BuildDecision:
    return BuildDecision.of(
        match_id=match_id(),
        outcome=BuildOutcome.BUILD,
        scope=UsageScope.RESEARCH,
        build_policy_version=CURRENT_BUILD_POLICY_VERSION,
        families=(
            FamilyDecision.included(CoverageFamily.MATCH),
            FamilyDecision.included(CoverageFamily.LINEUP),
            FamilyDecision.included(CoverageFamily.ODDS),
        ),
    )


class TestCanonicalMatchBuilder:
    def test_constroi_a_partida_a_partir_da_identidade_resolvida(self) -> None:
        partida = CanonicalMatchBuilder().build(
            decision=_decisao_completa(), identity=identity_facts()
        )
        assert isinstance(partida, Match)
        assert partida.id == match_id()
        assert partida.lifecycle is BUILT_LIFECYCLE

    def test_a_partida_construida_continua_SEM_resultado(self) -> None:
        """§32, §88. O primeiro write real não desfaz a decisão do PR-01."""
        partida = CanonicalMatchBuilder().build(
            decision=_decisao_completa(), identity=identity_facts()
        )
        for proibido in ("result", "final_score", "winner", "score", "outcome"):
            assert not hasattr(partida, proibido), (
                f"`{proibido}` apareceu em Match — qualquer caminho que descreva o "
                "minuto 63 passaria a poder ler o fim (ADR-0007)"
            )

    def test_recusa_construir_sem_decisao_autorizando(self) -> None:
        """§5. O construtor não reavalia — ele exige a decisão."""
        recusada = BuildDecision.of(
            match_id=match_id(),
            outcome=BuildOutcome.SKIP,
            scope=UsageScope.RESEARCH,
            build_policy_version=CURRENT_BUILD_POLICY_VERSION,
            families=(
                FamilyDecision.excluded(CoverageFamily.MATCH, FamilyExclusionReason.NOT_AVAILABLE),
            ),
            reason="pulada",
        )
        with pytest.raises(InvariantViolationError):
            CanonicalMatchBuilder().build(decision=recusada, identity=identity_facts())

    def test_recusa_identidade_de_outra_partida(self) -> None:
        with pytest.raises(InvariantViolationError, match="duas partidas"):
            CanonicalMatchBuilder().build(decision=_decisao_completa(), identity=identity_facts(7))


class TestCanonicalResultBuilder:
    def test_constroi_o_resultado_separado_da_partida(self) -> None:
        resultado = CanonicalResultBuilder().build(
            decision=_decisao_completa(),
            scores=read_score_facts(cenario_publico_com_odds().candidate),
        )
        assert isinstance(resultado, MatchResult)
        assert resultado.regular_time.home == 2
        assert resultado.regular_time.away == 1

    def test_placar_ausente_devolve_None_e_NUNCA_zero_a_zero(self) -> None:
        """§44, §89. Um `0-0` no lugar seria um empate sem gols que ninguém
        distingue de um empate sem gols de verdade."""
        resultado = CanonicalResultBuilder().build(
            decision=_decisao_completa(), scores=ScoreFacts()
        )
        assert resultado is None

    def test_meio_placar_tambem_e_ausencia(self) -> None:
        """`2-None` não é `2-0`. Completar o outro lado com zero é o §44
        acontecendo quando ninguém está olhando."""
        resultado = CanonicalResultBuilder().build(
            decision=_decisao_completa(), scores=ScoreFacts(regular_home=2)
        )
        assert resultado is None

    def test_prorrogacao_e_penaltis_ficam_None_na_V1(self) -> None:
        """§34. Não há papel semântico para eles, e derivá-los do tempo
        normal inventaria um jogo."""
        facts = read_score_facts(cenario_publico_com_odds().candidate)
        assert facts.extra_home is None
        assert facts.penalties_home is None
        resultado = CanonicalResultBuilder().build(decision=_decisao_completa(), scores=facts)
        assert resultado is not None
        assert resultado.extra_time is None
        assert resultado.penalties is None

    def test_conflito_de_placar_le_como_ausencia(self) -> None:
        """A fusão não escolheu; escolher aqui seria tomar por conta a
        decisão que ela recusou tomar (§45)."""
        facts = read_score_facts(placar_em_conflito().candidate)
        assert facts.regular_home is None


class TestCanonicalOddsBuilder:
    def test_duas_casas_viram_DUAS_observacoes_por_selecao(self) -> None:
        """§42, §93. `2.025` é um preço que casa nenhuma ofereceu."""
        cena = cenario_publico_com_odds()
        conjunto = odds_observations_of(cena.candidate)
        assert conjunto is not None

        observacoes = CanonicalOddsBuilder().build(
            decision=_decisao_completa(),
            observations=conjunto,
            match_id=match_id(),
            ingested_at=AGORA,
        )
        casas = {str(o.bookmaker) for o in observacoes}
        assert casas == {"bet365", "pinnacle"}

        mandantes = {
            str(o.bookmaker): o.decimal_odds for o in observacoes if o.selection.value == "HOME"
        }
        assert mandantes == {
            "bet365": Decimal("2.00"),
            "pinnacle": Decimal("2.05"),
        }
        assert Decimal("2.025") not in set(mandantes.values())

    def test_cada_selecao_do_mercado_vira_uma_observacao(self) -> None:
        cena = cenario_publico_com_odds()
        conjunto = odds_observations_of(cena.candidate)
        assert conjunto is not None
        observacoes = CanonicalOddsBuilder().build(
            decision=_decisao_completa(),
            observations=conjunto,
            match_id=match_id(),
            ingested_at=AGORA,
        )
        # duas casas x três seleções
        assert len(observacoes) == 6

    def test_o_instante_desconhecido_fica_None_e_nao_vira_kickoff(self) -> None:
        """§44. Preencher com o kickoff inventaria um fato plausível — que é
        o pior tipo."""
        cena = cenario_publico_com_odds()
        conjunto = odds_observations_of(cena.candidate)
        assert conjunto is not None
        observacoes = CanonicalOddsBuilder().build(
            decision=_decisao_completa(),
            observations=conjunto,
            match_id=match_id(),
            ingested_at=AGORA,
        )
        assert all(o.observed_at is None for o in observacoes)
        assert all(not o.observation_time_is_known for o in observacoes)

    def test_a_identidade_da_V1_nao_inclui_o_instante(self) -> None:
        """§43. Preservar o que o PR-03.2 entregou."""
        cena = cenario_publico_com_odds()
        conjunto = odds_observations_of(cena.candidate)
        assert conjunto is not None
        observacoes = CanonicalOddsBuilder().build(
            decision=_decisao_completa(),
            observations=conjunto,
            match_id=match_id(),
            ingested_at=AGORA,
        )
        chaves = {o.identity for o in observacoes}
        assert len(chaves) == len(observacoes)

    def test_sem_odds_o_conjunto_e_None_e_nao_vazio(self) -> None:
        """«a fonte não trabalha com odds» e «trabalha e não trouxe» são
        coisas diferentes."""
        assert odds_observations_of(sem_odds().candidate) is None


class TestCanonicalLineupBuilder:
    @staticmethod
    def _rascunho(*, resolvido: bool = True) -> LineupDraft:
        return LineupDraft.of(
            match_id=match_id(),
            team_id=CASA,
            entries=(
                LineupDraftEntry(
                    source_name="Goleiro",
                    status=LineupStatus.STARTER,
                    player_id=PlayerId.derive("pr042", "goleiro"),
                    shirt_number=1,
                ),
                LineupDraftEntry(
                    source_name="Camisa 10",
                    status=LineupStatus.STARTER,
                    player_id=(PlayerId.derive("pr042", "camisa10") if resolvido else None),
                    shirt_number=10,
                    captain=True,
                ),
            ),
            formation=None,
        )

    def test_constroi_com_PlayerId_canonico(self) -> None:
        escalacao = CanonicalLineupBuilder().build(
            decision=_decisao_completa(), draft=self._rascunho()
        )
        assert len(escalacao.entries) == 2
        assert escalacao.captain is not None

    def test_recusa_construir_com_jogador_nao_resolvido(self) -> None:
        """§36, §91. Nem derivado do nome, nem sorteado, nem «temporário»."""
        rascunho = self._rascunho(resolvido=False)
        assert rascunho.unresolved == ("Camisa 10",)
        with pytest.raises(InvariantViolationError, match="sem identidade canônica"):
            CanonicalLineupBuilder().build(decision=_decisao_completa(), draft=rascunho)

    def test_a_formacao_invalida_vira_ausencia_e_nao_erro(self) -> None:
        rascunho = replace(self._rascunho(), formation="4231")
        escalacao = CanonicalLineupBuilder().build(decision=_decisao_completa(), draft=rascunho)
        assert escalacao.formation is None


# ======================================================== a montagem ====


class TestCanonicalAssembler:
    def _inputs(self, cena: Cenario) -> MatchBuildInputs:
        return MatchBuildInputs(
            record=_veredito(cena),
            candidate=cena.candidate,
            identity=identity_facts(),
        )

    def test_monta_partida_resultado_e_odds(self) -> None:
        plano = CanonicalAssembler(policy=DEFAULT_RESEARCH_BUILD_POLICY).plan(
            self._inputs(cenario_publico_com_odds()), ingested_at=AGORA
        )
        assert plano.match is not None
        assert plano.result is not None
        assert len(plano.odds) == 6

    def test_o_comercial_monta_a_partida_e_NAO_as_odds(self) -> None:
        plano = CanonicalAssembler(policy=DEFAULT_COMMERCIAL_BUILD_POLICY).plan(
            self._inputs(cenario_publico_com_odds()), ingested_at=AGORA
        )
        assert plano.match is not None
        assert plano.odds == ()
        assert CoverageFamily.ODDS in plano.decision.excluded_by_license

    def test_sem_identidade_canonica_o_build_recusa_em_vez_de_inventar(self) -> None:
        """§27. Criar um `MatchId` aqui produziria uma partida que nenhuma
        resolução provou existir."""
        entrada = replace(self._inputs(cenario_publico_com_odds()), identity=None)
        plano = CanonicalAssembler(policy=DEFAULT_RESEARCH_BUILD_POLICY).plan(
            entrada, ingested_at=AGORA
        )
        assert plano.decision.outcome is BuildOutcome.SKIP
        assert plano.match is None
        assert "não tem identidade canônica" in (plano.decision.reason or "")

    def test_a_ausencia_de_resultado_fica_ANOTADA(self) -> None:
        calendario = replace(DEFAULT_RESEARCH_BUILD_POLICY, require_result=False)
        plano = CanonicalAssembler(policy=calendario).plan(
            self._inputs(sem_placar()), ingested_at=AGORA
        )
        assert plano.match is not None
        assert plano.result is None
        assert CanonicalFactType.MATCH_RESULT in plano.notes

    def test_recusa_avaliacao_de_outra_partida(self) -> None:
        with pytest.raises(ValidationError, match="duas partidas"):
            MatchBuildInputs(
                record=_veredito(cenario_publico_com_odds(0)),
                candidate=cenario_publico_com_odds(1).candidate,
            )


class TestRegistrosDeLinhagem:
    def test_partida_recusada_produz_registro_mesmo_assim(self) -> None:
        """Sem ele, «o que aconteceu com esta partida» não teria resposta."""
        plano = CanonicalAssembler(policy=DEFAULT_RESEARCH_BUILD_POLICY).plan(
            MatchBuildInputs(
                record=_veredito(placar_em_conflito()),
                candidate=placar_em_conflito().candidate,
                identity=identity_facts(),
            ),
            ingested_at=AGORA,
        )
        registros = records_of(plano, build_run_id="22222222-2222-4222-8222-222222222222")
        assert len(registros) == 1
        assert registros[0].status is BuildRecordStatus.SKIPPED
        assert registros[0].fact_id is None

    def test_conflito_de_escrita_vira_FAILED_com_motivo(self) -> None:
        """§62. Nada foi sobrescrito, e o registro diz isso."""
        cena = cenario_publico_com_odds()
        plano = CanonicalAssembler(policy=DEFAULT_RESEARCH_BUILD_POLICY).plan(
            MatchBuildInputs(
                record=_veredito(cena),
                candidate=cena.candidate,
                identity=identity_facts(),
            ),
            ingested_at=AGORA,
        )
        registros = records_of(
            plano,
            build_run_id="22222222-2222-4222-8222-222222222222",
            match_outcome=MatchWriteOutcome.CONFLICT,
        )
        partida = next(r for r in registros if r.fact_type is CanonicalFactType.MATCH)
        assert partida.status is BuildRecordStatus.FAILED
        assert partida.fact_id is None
        assert "DISCORDA" in (partida.reason or "")

    def test_registro_materializado_precisa_do_id_do_fato(self) -> None:
        with pytest.raises(ValidationError, match="sem id do fato"):
            CanonicalBuildRecord(
                id="a",
                build_run_id="b",
                match_id=match_id(),
                fact_type=CanonicalFactType.MATCH,
                source_fusion_group_id="g",
                quality_assessment_id="q",
                status=BuildRecordStatus.BUILT,
            )

    def test_registro_sem_avaliacao_e_recusado(self) -> None:
        """§50. «Por que este fato entrou no corpus» ficaria sem resposta."""
        with pytest.raises(ValidationError, match="sem avaliação"):
            CanonicalBuildRecord(
                id="a",
                build_run_id="b",
                match_id=match_id(),
                fact_type=CanonicalFactType.MATCH,
                source_fusion_group_id="g",
                quality_assessment_id="  ",
                status=BuildRecordStatus.SKIPPED,
            )

    def test_registro_sem_grupo_de_fusao_e_recusado(self) -> None:
        """§47, §48: a linhagem para trás se romperia no primeiro elo."""
        with pytest.raises(ValidationError, match="sem grupo de fusão"):
            CanonicalBuildRecord(
                id="a",
                build_run_id="b",
                match_id=match_id(),
                fact_type=CanonicalFactType.MATCH,
                source_fusion_group_id="",
                quality_assessment_id="q",
                status=BuildRecordStatus.SKIPPED,
            )


# ==================================================== a execução ====


class TestCanonicalBuildRun:
    def _execucao(self) -> CanonicalBuildRun:
        return CanonicalBuildRun.start(
            quality_run_id="11111111-1111-4111-8111-111111111111",
            input_fusion_run_ids=("33333333-3333-4333-8333-333333333333",),
            build_policy_version=CURRENT_BUILD_POLICY_VERSION,
            build_policy_fingerprint=policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY),
            scope=UsageScope.RESEARCH,
            quality_policy_version=DEFAULT_QUALITY_POLICY.version,
            at=AGORA,
            triggered_by=ATOR,
        )

    def test_guarda_as_DUAS_versoes_de_politica(self) -> None:
        """§21. Um build é explicável por duas políticas, e ter de buscar a
        segunda em outra tabela faz alguém não buscar."""
        execucao = self._execucao()
        assert execucao.build_policy_version == CURRENT_BUILD_POLICY_VERSION
        assert execucao.quality_policy_version == DEFAULT_QUALITY_POLICY.version

    def test_execucao_concluida_e_imutavel(self) -> None:
        concluida = self._execucao().complete(
            counts=BuildCounts(records_attempted=1, records_built=1), at=AGORA
        )
        with pytest.raises(ConflictError, match="imutável"):
            concluida.complete(counts=BuildCounts(), at=AGORA)

    def test_um_fato_falhado_impede_declarar_conclusao(self) -> None:
        """§66. Nunca mentir sobre o que o corpus tem."""
        execucao = self._execucao().complete(
            counts=BuildCounts(records_attempted=2, records_built=1, records_failed=1),
            at=AGORA,
        )
        assert execucao.status is RunStatus.FAILED
        assert "não puderam ser construídos" in (execucao.failure_reason or "")

    def test_revisao_leva_a_completed_with_review(self) -> None:
        execucao = self._execucao().complete(
            counts=BuildCounts(records_attempted=2, records_built=1, records_review_required=1),
            at=AGORA,
        )
        assert execucao.status is RunStatus.COMPLETED_WITH_REVIEW

    def test_contagens_precisam_fechar(self) -> None:
        with pytest.raises(ValidationError, match="classificadas"):
            BuildCounts(records_attempted=5, records_built=2).assert_consistent()

    def test_o_corpus_publicavel_continua_barrado(self) -> None:
        """§110, §111. O que sai daqui são FATOS, não uma versão do corpus.

        A GUARDA PASSOU A IMPORTAR MAIS, e não menos, depois do PR-04.3:
        enquanto a versão publicada não existia, confundir as duas era
        impossível por ausência. Agora as duas existem, e o que separa um
        recorte congelado de um registro global que cresce é esta recusa.
        """
        with pytest.raises(InvariantViolationError, match="versão publicada"):
            assert_not_a_published_corpus(self._execucao())


# ================================================== o caso de uso ====


def _montar_build(
    *,
    identidades: FakeCanonicalIdentityReader,
    escritor: FakeCanonicalRegistryWriter,
    avaliacoes: FakeQualityAssessmentRepository,
    execucoes_de_qualidade: FakeQualityRunRepository,
    policy: CanonicalBuildPolicy = DEFAULT_RESEARCH_BUILD_POLICY,
    build_runs: FakeCanonicalBuildRunRepository | None = None,
    registros: FakeCanonicalBuildRecordRepository | None = None,
) -> RunCanonicalBuild:
    return RunCanonicalBuild(
        quality_runs=execucoes_de_qualidade,
        assessments=avaliacoes,
        identities=identidades,
        registry=escritor,
        build_runs=build_runs or FakeCanonicalBuildRunRepository(),
        records=registros or FakeCanonicalBuildRecordRepository(),
        clock=FrozenClock(AGORA),
        audit=FakeAudit(),
        policy=policy,
    )


async def _com_avaliacao(
    cenas: Sequence[Cenario],
) -> tuple[QualityRun, FakeQualityRunRepository, FakeQualityAssessmentRepository]:
    """Roda a avaliação e devolve o cenário pronto para o build.

    O BUILD LÊ A AVALIAÇÃO DO REPOSITÓRIO, e não de um objeto que o teste
    montou: é o round-trip que prova que o veredito PERSISTIDO é o que
    autoriza a construção (§50).
    """
    fusao = fusion_run_concluida()
    execucoes = FakeQualityRunRepository()
    avaliacoes = FakeQualityAssessmentRepository()
    saida = await RunHistoricalQualityAssessment(
        fusion_runs=FakeFusionRunRepository(fusao),
        quality_runs=execucoes,
        assessments=avaliacoes,
        clock=FrozenClock(AGORA),
        audit=FakeAudit(),
    ).execute(
        actor=ATOR,
        fusion_run_ids=[fusao.id],
        batches=um_lote([c.evidence() for c in cenas]),
    )
    return saida.run, execucoes, avaliacoes


class TestRunCanonicalBuild:
    async def test_a_cadeia_completa_produz_fatos_canonicos(self) -> None:
        """§112: candidato → avaliação → decisão → fato persistido."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        escritor = FakeCanonicalRegistryWriter()
        caso = _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=escritor,
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
        )

        saida = await caso.execute(
            actor=ATOR,
            quality_run_id=execucao.id,
            batches=um_lote_de_candidatos(cenas),
        )

        assert saida.run.status is RunStatus.COMPLETED
        assert saida.run.counts.records_built == 1
        assert len(escritor.matches) == 1
        assert len(escritor.results) == 1
        assert len(escritor.odds) == 6

    async def test_o_match_persistido_continua_sem_resultado(self) -> None:
        """§87, §88. O resultado existe — em outro fato."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        escritor = FakeCanonicalRegistryWriter()
        await _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=escritor,
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        partida = next(iter(escritor.matches.values()))
        assert not hasattr(partida, "result")
        assert escritor.results[partida.id].regular_time.home == 2

    async def test_pesquisa_e_comercio_coexistem_sobre_a_MESMA_avaliacao(self) -> None:
        """§52, §86. Dois builds, mesma partida, famílias diferentes."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        identidades = FakeCanonicalIdentityReader(identity_facts(0))
        build_runs = FakeCanonicalBuildRunRepository()
        registros = FakeCanonicalBuildRecordRepository()

        pesquisa = await _montar_build(
            identidades=identidades,
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            policy=DEFAULT_RESEARCH_BUILD_POLICY,
            build_runs=build_runs,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        comercial = await _montar_build(
            identidades=identidades,
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            policy=DEFAULT_COMMERCIAL_BUILD_POLICY,
            build_runs=build_runs,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))

        assert pesquisa.run.id != comercial.run.id
        assert pesquisa.run.scope is UsageScope.RESEARCH
        assert comercial.run.scope is UsageScope.COMMERCIAL
        assert CoverageFamily.ODDS in pesquisa.decisions[0].included_families
        assert CoverageFamily.ODDS in comercial.decisions[0].excluded_by_license
        # A execução ANTERIOR fica exatamente como estava.
        assert build_runs.runs[pesquisa.run.id].counts.records_built == 1
        assert len(await build_runs.for_quality_run(execucao.id)) == 2

    async def test_o_mesmo_fato_e_REUSADO_e_ganha_linhagem_nova(self) -> None:
        """§97. Uma partida canônica, duas linhagens de build."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        escritor = FakeCanonicalRegistryWriter()
        identidades = FakeCanonicalIdentityReader(identity_facts(0))
        registros = FakeCanonicalBuildRecordRepository()

        primeiro = await _montar_build(
            identidades=identidades,
            escritor=escritor,
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        segundo = await _montar_build(
            identidades=identidades,
            escritor=escritor,
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))

        assert primeiro.run.counts.records_built == 1
        assert segundo.run.counts.records_reused == 1
        # UM fato canônico...
        assert len(escritor.matches) == 1
        # ...e DUAS linhagens.
        linhagem = await registros.for_match(match_id(0))
        execucoes_na_linhagem = {r.build_run_id for r in linhagem}
        assert execucoes_na_linhagem == {primeiro.run.id, segundo.run.id}

    async def test_fato_conflitante_nao_usa_last_write_wins(self) -> None:
        """§62, §98. Nada é sobrescrito; a execução termina em FAILED."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        escritor = FakeCanonicalRegistryWriter()
        # Uma partida JÁ existe, com outro confronto.
        invertida = replace(
            identity_facts(0),
            home_team_id=identity_facts(0).away_team_id,
            away_team_id=CASA,
        )
        divergente = CanonicalMatchBuilder().build(decision=_decisao_completa(), identity=invertida)
        escritor.matches[divergente.id] = divergente

        saida = await _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=escritor,
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))

        assert saida.run.status is RunStatus.FAILED
        assert saida.run.counts.records_failed == 1
        # O fato anterior continua exatamente como estava.
        assert escritor.matches[divergente.id] is divergente

    async def test_idempotencia_nao_duplica_odds(self) -> None:
        """§96. A identidade da V1 é (partida, casa, mercado, seleção, linha),
        e o instante não entra nela — reler o arquivo não cria a segunda."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        escritor = FakeCanonicalRegistryWriter()
        identidades = FakeCanonicalIdentityReader(identity_facts(0))

        for _ in range(2):
            await _montar_build(
                identidades=identidades,
                escritor=escritor,
                avaliacoes=avaliacoes,
                execucoes_de_qualidade=execucoes,
            ).execute(
                actor=ATOR,
                quality_run_id=execucao.id,
                batches=um_lote_de_candidatos(cenas),
            )
        assert len(escritor.odds) == 6
        assert len(escritor.matches) == 1

    async def test_partida_sem_identidade_e_pulada_e_registrada(self) -> None:
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        registros = FakeCanonicalBuildRecordRepository()
        saida = await _montar_build(
            identidades=FakeCanonicalIdentityReader(),  # nenhuma identidade
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        assert saida.run.counts.records_skipped == 1
        linhagem = await registros.for_match(match_id(0))
        assert linhagem[0].status is BuildRecordStatus.SKIPPED

    async def test_a_decisao_por_familia_e_gravada(self) -> None:
        """§20. «As odds desta partida sumiram?» tem resposta."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        registros = FakeCanonicalBuildRecordRepository()
        saida = await _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            policy=DEFAULT_COMMERCIAL_BUILD_POLICY,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        familias = await registros.family_decisions_of(saida.run.id, match_id(0))
        odds = next(f for f in familias if f.family is CoverageFamily.ODDS)
        assert odds.outcome is FamilyOutcome.EXCLUDED
        assert odds.reason is FamilyExclusionReason.LICENSE_POLICY

    async def test_recusa_construir_sobre_avaliacao_que_falhou(self) -> None:
        execucoes = FakeQualityRunRepository()
        falha = QualityRun.start(
            inputs=(QualityRunInput(fusion_run_id="f"),),
            policy_version=DEFAULT_QUALITY_POLICY.version,
            policy_fingerprint=policy_fingerprint(DEFAULT_QUALITY_POLICY),
            at=AGORA,
            triggered_by=ATOR,
        ).fail(reason="worker morto", at=AGORA)
        execucoes.runs[falha.id] = falha

        caso = _montar_build(
            identidades=FakeCanonicalIdentityReader(),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=FakeQualityAssessmentRepository(),
            execucoes_de_qualidade=execucoes,
        )
        with pytest.raises(ConflictError, match="não produziu saída utilizável"):
            await caso.execute(
                actor=ATOR, quality_run_id=falha.id, batches=um_lote_de_candidatos(())
            )

    async def test_avaliacao_inexistente_e_nao_encontrada(self) -> None:
        caso = _montar_build(
            identidades=FakeCanonicalIdentityReader(),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=FakeQualityAssessmentRepository(),
            execucoes_de_qualidade=FakeQualityRunRepository(),
        )
        with pytest.raises(NotFoundError):
            await caso.execute(
                actor=ATOR, quality_run_id="fantasma", batches=um_lote_de_candidatos(())
            )

    async def test_a_impressao_do_build_e_deterministica(self) -> None:
        """§53, §54: mesma entrada, mesmas políticas, mesma impressão — com
        ids de execução diferentes."""
        cenas = cenarios(3)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        identidades = FakeCanonicalIdentityReader(*(identity_facts(n) for n in range(3)))
        impressoes = []
        for _ in range(2):
            saida = await _montar_build(
                identidades=identidades,
                escritor=FakeCanonicalRegistryWriter(),
                avaliacoes=avaliacoes,
                execucoes_de_qualidade=execucoes,
            ).execute(
                actor=ATOR,
                quality_run_id=execucao.id,
                batches=um_lote_de_candidatos(cenas),
            )
            impressoes.append(saida.run.output_fingerprint)
        assert impressoes[0] is not None
        assert impressoes[0] == impressoes[1]

    async def test_falha_no_lote_nao_declara_sucesso(self) -> None:
        """§100."""
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        build_runs = FakeCanonicalBuildRunRepository()
        caso = _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            build_runs=build_runs,
        )

        async def explode() -> AsyncIterator[BuildCandidateBatch]:
            yield BuildCandidateBatch(candidates=(cenas[0].candidate,))
            raise RuntimeError("terceiro lote quebrou")

        with pytest.raises(RuntimeError):
            await caso.execute(actor=ATOR, quality_run_id=execucao.id, batches=explode())
        gravada = next(iter(build_runs.runs.values()))
        assert gravada.status is RunStatus.FAILED


class TestConsultas:
    async def test_get_build_run_e_linhagem(self) -> None:
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        build_runs = FakeCanonicalBuildRunRepository()
        registros = FakeCanonicalBuildRecordRepository()
        saida = await _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            build_runs=build_runs,
            registros=registros,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))

        lida = await GetCanonicalBuildRun(build_runs=build_runs).execute(saida.run.id)
        assert lida.id == saida.run.id

        linhagem = await GetMatchLineage(records=registros).execute(match_id(0))
        assert {r.fact_type for r in linhagem} >= {
            CanonicalFactType.MATCH,
            CanonicalFactType.MATCH_RESULT,
            CanonicalFactType.ODDS_OBSERVATION,
        }
        # Cada fato aponta para a avaliação que o autorizou (§50).
        assert all(r.quality_assessment_id for r in linhagem)
        assert all(r.source_fusion_group_id for r in linhagem)

        with pytest.raises(NotFoundError):
            await GetCanonicalBuildRun(build_runs=build_runs).execute("fantasma")


async def um_lote_de_candidatos(
    cenas: Sequence[Cenario],
) -> AsyncIterator[BuildCandidateBatch]:
    """Um lote com todos os candidatos. A construção pagina por dentro."""
    yield BuildCandidateBatch(candidates=tuple(c.candidate for c in cenas))


# ==================================================== ausência é ausência ==


class TestMissingNuncaViraZero:
    """§44, §94 — o defeito mais caro que um corpus de futebol pode ter.

    Ele é caro porque é PLAUSÍVEL: um `0-0` no lugar de um placar ausente e um
    `xG = 0` no lugar de um xG que a fonte não publica passam por qualquer
    validação, e inflam para sempre a contagem de empates sem gol e a média de
    xG de toda temporada mal ingerida.
    """

    def test_nenhum_fato_canonico_representa_xg(self) -> None:
        """A fonte traz xG e o corpus desta fase NÃO o materializa — nem como
        valor, nem como zero, nem como coluna vazia esperando um.

        A AUSÊNCIA É DO CONTRATO e está declarada: não há família de cobertura
        para estatística analítica, não há construtor, e não há tabela. É
        diferente de «gravamos zero», e a diferença é o §44.
        """
        from sports_intelligence.domain.matches.result import MatchResult, Score

        for tipo in (Match, MatchResult, Score):
            campos = set(getattr(tipo, "__dataclass_fields__", {}))
            assert not {c for c in campos if "xg" in c.lower()}, (
                f"{tipo.__name__} ganhou um campo de xG — o corpus desta fase não "
                "materializa estatística analítica, e um campo aqui viraria zero "
                "na primeira fonte que não a publica"
            )

    def test_o_placar_ausente_atravessa_a_montagem_como_ausencia(self) -> None:
        """Do candidato ao plano: em nenhum ponto ele vira `0-0`."""
        calendario = replace(DEFAULT_RESEARCH_BUILD_POLICY, require_result=False)
        cena = sem_placar()

        facts = read_score_facts(cena.candidate)
        assert facts.is_empty
        assert facts.regular_home is None
        assert facts.regular_away is None

        plano = CanonicalAssembler(policy=calendario).plan(
            MatchBuildInputs(
                record=_veredito(cena),
                candidate=cena.candidate,
                identity=identity_facts(),
            ),
            ingested_at=AGORA,
        )
        assert plano.match is not None
        assert plano.result is None
        # E o registro de linhagem DIZ que o resultado não foi construído, em
        # vez de simplesmente não existir (§20).
        registros = records_of(
            plano,
            build_run_id="33333333-3333-4333-8333-333333333333",
            match_outcome=MatchWriteOutcome.INSERTED,
        )
        do_resultado = next(r for r in registros if r.fact_type is CanonicalFactType.MATCH_RESULT)
        assert do_resultado.status is BuildRecordStatus.SKIPPED
        assert do_resultado.fact_id is None
        assert "NÃO vira 0-0" in (do_resultado.reason or "")

    def test_odds_sem_instante_nao_recebem_um_inventado(self) -> None:
        """§43, §44. Nem o kickoff, nem `now()`, nem o instante da leitura."""
        cena = cenario_publico_com_odds()
        conjunto = odds_observations_of(cena.candidate)
        assert conjunto is not None
        observacoes = CanonicalOddsBuilder().build(
            decision=_decisao_completa(),
            observations=conjunto,
            match_id=match_id(),
            ingested_at=AGORA,
        )
        assert observacoes
        for observacao in observacoes:
            assert observacao.observed_at is None
            # E o instante NÃO entra na identidade da V1 (§43).
            assert AGORA not in observacao.identity


# ============================ identidade de configuração (PR-04.2.1) ==


class TestImpressaoDaPolitica:
    """§36, §37, §38 — versão + impressão do conteúdo.

        identidade de configuração = versão + impressão

    A versão pega a mudança declarada; a impressão pega a que ninguém
    declarou. Sem as duas, «sob qual política este corpus foi construído» tem
    resposta ambígua exatamente quando alguém editou e esqueceu de subir.
    """

    def test_a_mesma_politica_produz_a_mesma_impressao(self) -> None:
        """§38: a serialização é determinística, e não depende de ordem de
        `dict`, de `repr` nem de endereço de memória."""
        gemea = replace(DEFAULT_RESEARCH_BUILD_POLICY)
        assert policy_fingerprint(gemea) == policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY)
        # E é estável entre chamadas — um `set` reordenado quebraria isto.
        assert policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY) == policy_fingerprint(
            DEFAULT_RESEARCH_BUILD_POLICY
        )

    def test_mesma_VERSAO_e_conteudo_diferente_dao_impressoes_diferentes(self) -> None:
        """O caso que a versão sozinha não pega."""
        adulterada = replace(
            DEFAULT_RESEARCH_BUILD_POLICY,
            optional_families=frozenset({CoverageFamily.ODDS}),
        )
        assert adulterada.version == DEFAULT_RESEARCH_BUILD_POLICY.version
        assert policy_fingerprint(adulterada) != policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY)

    def test_pesquisa_e_comercio_tem_impressoes_diferentes(self) -> None:
        """Elas têm a MESMA versão e produzem corpus diferentes — se a
        impressão não as distinguisse, dois builds seriam indistinguíveis
        pelos metadados que gravamos."""
        assert DEFAULT_RESEARCH_BUILD_POLICY.version == DEFAULT_COMMERCIAL_BUILD_POLICY.version
        assert policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY) != policy_fingerprint(
            DEFAULT_COMMERCIAL_BUILD_POLICY
        )

    async def test_a_execucao_grava_a_impressao_da_politica_que_rodou(self) -> None:
        cenas = (cenario_publico_com_odds(0),)
        execucao, execucoes, avaliacoes = await _com_avaliacao(cenas)
        build_runs = FakeCanonicalBuildRunRepository()
        saida = await _montar_build(
            identidades=FakeCanonicalIdentityReader(identity_facts(0)),
            escritor=FakeCanonicalRegistryWriter(),
            avaliacoes=avaliacoes,
            execucoes_de_qualidade=execucoes,
            policy=DEFAULT_COMMERCIAL_BUILD_POLICY,
            build_runs=build_runs,
        ).execute(actor=ATOR, quality_run_id=execucao.id, batches=um_lote_de_candidatos(cenas))
        gravada = build_runs.runs[saida.run.id]
        assert gravada.build_policy_fingerprint == policy_fingerprint(
            DEFAULT_COMMERCIAL_BUILD_POLICY
        )
        assert gravada.build_policy_fingerprint != policy_fingerprint(DEFAULT_RESEARCH_BUILD_POLICY)
