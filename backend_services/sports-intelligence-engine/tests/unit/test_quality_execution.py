"""A EXECUÇÃO da avaliação de qualidade — o que o PR-04.1 não tinha.

O QUE ESTES TESTES PROTEGEM. O PR-04.1 provou que qualidade, cobertura e
licença não colapsam num score. Aqui a pergunta é outra e mais operacional:
esse veredito consegue ser PRODUZIDO sobre entrada real, GRAVADO, e reproduzido
meses depois sob a política que de fato o decidiu?

Metade dos casos continua verificando que alguma coisa NÃO aconteceu: ausência
que não vira zero, cobertura não declarada que não vira 0%, conflito opcional
que não derruba a partida, execução concluída que não aceita ser reescrita.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence

import pytest

from sports_intelligence.application.use_cases.quality import (
    GetQualityRun,
    ListQualityAssessments,
    RunHistoricalQualityAssessment,
)
from sports_intelligence.domain.fusion.runs import FusionRun
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.coverage import CoverageFamily, CoverageState
from sports_intelligence.domain.quality.issues import IssueCode, Severity
from sports_intelligence.domain.quality.licensing import UsageEligibility
from sports_intelligence.domain.quality.policy import (
    DEFAULT_QUALITY_POLICY,
    HistoricalQualityPolicy,
)
from sports_intelligence.domain.quality.runs import (
    QUALITY_ASSESSOR,
    MatchQualityRecord,
    QualityCounts,
    QualityRun,
    QualityRunInput,
    assert_run_is_consumable,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.resolution.versions import (
    CURRENT_FUSION_POLICY_VERSION,
    PolicyVersion,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from sports_intelligence.domain.shared.fingerprint import policy_fingerprint
from sports_intelligence.domain.shared.provenance import LicenseClass
from sports_intelligence.historical.quality.assessor import (
    CORE_ROLES,
    SCORE_ROLES,
    CandidateEvidence,
    HistoricalQualityAssessor,
)
from sports_intelligence.ports.clock import FrozenClock
from tests.support.build_doubles import (
    FakeAudit,
    FakeFusionRunRepository,
    FakeQualityAssessmentRepository,
    FakeQualityRunRepository,
)
from tests.support.build_fixtures import (
    AGORA,
    CONFIANCAS_BOAS,
    Cenario,
    cenario_publico_com_odds,
    cenarios,
    formacao_em_conflito,
    fusion_run_concluida,
    lotes,
    placar_em_conflito,
    sem_odds,
    sem_placar,
    um_lote,
)

ATOR = Actor.service("historical-quality-assessor")
IMPRESSAO = policy_fingerprint(DEFAULT_QUALITY_POLICY)
EXECUCAO_DE_TESTE = "44444444-4444-4444-8444-444444444444"


def _avaliar(
    cena: Cenario,
    *,
    confidences: Mapping[SubjectType, float] | None = None,
    policy: HistoricalQualityPolicy = DEFAULT_QUALITY_POLICY,
) -> MatchQualityRecord:
    return HistoricalQualityAssessor(policy=policy).assess(
        cena.evidence(confidences=confidences), quality_run_id=EXECUCAO_DE_TESTE
    )


def _execucao(
    inputs: tuple[QualityRunInput, ...] = (QualityRunInput(fusion_run_id="fusao-1"),),
) -> QualityRun:
    return QualityRun.start(
        inputs=inputs,
        policy_version=DEFAULT_QUALITY_POLICY.version,
        policy_fingerprint=IMPRESSAO,
        at=AGORA,
        triggered_by=ATOR,
    )


# ====================================================== a execução ====


class TestQualityRun:
    def test_nasce_rodando_com_a_versao_da_politica(self) -> None:
        execucao = _execucao()
        assert execucao.status is RunStatus.RUNNING
        assert execucao.policy_version == DEFAULT_QUALITY_POLICY.version
        assert execucao.completed_at is None

    def test_recusa_execucao_sem_entrada(self) -> None:
        """Uma avaliação sem fusão de entrada avalia o quê?"""
        with pytest.raises(ValidationError, match="sem entrada"):
            QualityRun(
                id="x",
                inputs=(),
                policy_version=PolicyVersion(major=1, minor=0),
                policy_fingerprint=IMPRESSAO,
                status=RunStatus.RUNNING,
                started_at=AGORA,
                triggered_by=ATOR,
            )

    def test_recusa_a_mesma_fusao_duas_vezes(self) -> None:
        """Os candidatos dela entrariam em dobro e as contagens mentiriam."""
        with pytest.raises(ValidationError, match="duas vezes"):
            _execucao(
                (
                    QualityRunInput(fusion_run_id="fusao-1"),
                    QualityRunInput(fusion_run_id="fusao-1"),
                )
            )

    def test_conclusao_deriva_o_status_das_contagens(self) -> None:
        """`REVIEW_REQUIRED` leva a `COMPLETED_WITH_REVIEW`, e não a
        `COMPLETED`: os dois são sucesso, e o segundo diz «nada a fazer»."""
        limpa = _execucao().complete(
            counts=QualityCounts(records_examined=2, eligible=2), at=AGORA
        )
        com_revisao = _execucao().complete(
            counts=QualityCounts(records_examined=2, eligible=1, review_required=1),
            at=AGORA,
        )
        assert limpa.status is RunStatus.COMPLETED
        assert com_revisao.status is RunStatus.COMPLETED_WITH_REVIEW

    def test_execucao_concluida_e_imutavel(self) -> None:
        """§51. Política nova produz execução nova; a anterior fica."""
        concluida = _execucao().complete(
            counts=QualityCounts(records_examined=1, eligible=1), at=AGORA
        )
        with pytest.raises(ConflictError, match="imutável"):
            concluida.complete(counts=QualityCounts(), at=AGORA)
        with pytest.raises(ConflictError, match="imutável"):
            concluida.fail(reason="tarde demais", at=AGORA)

    def test_contagens_precisam_fechar(self) -> None:
        """A diferença silenciosa é onde um lote perdido se esconde."""
        with pytest.raises(ValidationError, match="classificadas"):
            QualityCounts(records_examined=10, eligible=3).assert_consistent()

    def test_falha_exige_motivo(self) -> None:
        falha = _execucao().fail(reason="DependencyError", at=AGORA)
        assert falha.status is RunStatus.FAILED
        assert falha.failure_reason == "DependencyError"

    def test_a_impressao_da_politica_pega_o_limiar_editado_sem_subir_versao(
        self,
    ) -> None:
        """A VERSÃO NÃO BASTA. Alguém edita um piso e esquece de subir o
        número: as duas execuções ficam rotuladas `1.0` e decidem diferente."""
        adulterada = HistoricalQualityPolicy(
            version=DEFAULT_QUALITY_POLICY.version,
            severities=dict(DEFAULT_QUALITY_POLICY.severities),
            critical_dimensions=DEFAULT_QUALITY_POLICY.critical_dimensions,
            minimums={**DEFAULT_QUALITY_POLICY.minimums},
            identity_minimums={
                **DEFAULT_QUALITY_POLICY.identity_minimums,
                SubjectType.MATCH: 0.10,
            },
        )
        assert adulterada.version == DEFAULT_QUALITY_POLICY.version
        assert policy_fingerprint(adulterada) != IMPRESSAO

    def test_run_nao_consumivel_e_recusada(self) -> None:
        """§66: construir sobre uma avaliação FAILED daria um corpus que
        parece completo e não é."""
        falha = _execucao().fail(reason="worker morto", at=AGORA)
        with pytest.raises(ConflictError, match="não produziu"):
            assert_run_is_consumable(falha)


# ============================================== o avaliador em ação ====


class TestAvaliacaoDeCandidatoReal:
    def test_o_cenario_saudavel_e_elegivel(self) -> None:
        registro = _avaliar(cenario_publico_com_odds())
        assert registro.eligibility is BuildEligibility.ELIGIBLE
        assert registro.assessment.reason is None

    def test_a_cobertura_de_odds_e_disponibilidade_e_nao_medida(self) -> None:
        """§13. Não existe denominador honesto para «quantas casas deveriam
        ter cotado esta partida» — inventar um daria uma fração que parece
        medida e não é."""
        cobertura = _avaliar(cenario_publico_com_odds()).assessment.coverage
        odds = cobertura.of_family(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.state is CoverageState.AVAILABILITY_ONLY
        assert odds.available_count == 2
        assert odds.expected_count is None
        assert odds.ratio is None

    def test_familias_fora_do_contrato_saem_nao_declaradas(self) -> None:
        """§20 do PR-04.1: nomear a ausência em vez de esquecê-la.

        `EVENT = NOT_DECLARED` diz «o contrato desta fase não carrega evento»;
        `EVENT = 0%` diria «a fonte falhou», e são coisas diferentes.
        """
        cobertura = _avaliar(cenario_publico_com_odds()).assessment.coverage
        for familia in (
            CoverageFamily.EVENT,
            CoverageFamily.SPATIAL,
            CoverageFamily.TRACKING,
        ):
            declarada = cobertura.of_family(familia)
            assert declarada is not None
            assert declarada.state is CoverageState.NOT_DECLARED
            assert declarada.expected_count is None
            assert declarada.ratio is None

    def test_a_licenca_e_por_familia_e_nao_global(self) -> None:
        """§19, o cenário central: núcleo público, odds `RESEARCH_ONLY`."""
        pegada = _avaliar(cenario_publico_com_odds()).assessment.usage.footprint
        assert pegada.by_family[CoverageFamily.MATCH] == frozenset(
            {LicenseClass.PUBLIC_DOMAIN}
        )
        assert pegada.by_family[CoverageFamily.ODDS] == frozenset(
            {LicenseClass.RESEARCH_ONLY}
        )

    def test_licenca_restrita_nao_reprova_a_qualidade_tecnica(self) -> None:
        """§84. A partida continua tecnicamente elegível; o que muda é o
        veredito de USO, que roda ao lado com resposta própria."""
        avaliacao = _avaliar(cenario_publico_com_odds()).assessment
        assert avaliacao.eligibility is BuildEligibility.ELIGIBLE
        assert avaliacao.usage.research is UsageEligibility.ELIGIBLE
        assert CoverageFamily.ODDS in avaliacao.usage.commercial_blockers

    def test_o_comercial_passa_quando_as_odds_podem_sair(self) -> None:
        """A exclusão declarada do §36 do PR-04.1, exercitada de ponta a ponta:
        a política de qualidade declara ODDS descartável, e o veredito
        comercial considera o candidato SEM ela."""
        avaliacao = _avaliar(cenario_publico_com_odds()).assessment
        assert DEFAULT_QUALITY_POLICY.commercially_droppable == frozenset(
            {CoverageFamily.ODDS}
        )
        assert avaliacao.usage.commercial is UsageEligibility.ELIGIBLE

    def test_licenca_restrita_vira_problema_INFO_e_nao_defeito(self) -> None:
        """§16, §30: o problema aparece no MESMO relatório e sua dimensão de
        qualidade é `None` — é assim que o tipo diz que não é qualidade."""
        avaliacao = _avaliar(cenario_publico_com_odds()).assessment
        restricoes = [
            p for p in avaliacao.issues if p.code is IssueCode.LICENSE_RESTRICTED
        ]
        assert restricoes
        assert all(p.dimension is None for p in restricoes)
        assert DEFAULT_QUALITY_POLICY.severity_of(IssueCode.LICENSE_RESTRICTED) is (
            Severity.INFO
        )

    def test_placar_ausente_nao_vira_zero_e_nao_reprova(self) -> None:
        """§44 e §89. Ausência é ausência: ela vira `MISSING_RESULT`, que a
        política pesa como WARNING — e não um `0-0` que ninguém distingue de
        um empate sem gols de verdade."""
        registro = _avaliar(sem_placar())
        codigos = {p.code for p in registro.assessment.issues}
        assert IssueCode.MISSING_RESULT in codigos
        assert registro.eligibility is BuildEligibility.ELIGIBLE
        assert registro.assessment.quality.completeness == pytest.approx(0.0)

    def test_conflito_de_placar_e_bloqueante(self) -> None:
        """§45. Uma das fontes está errada sobre um fato público e
        verificável; escolher uma esconderia um problema que alguém precisa
        ver."""
        registro = _avaliar(placar_em_conflito())
        codigos = {p.code for p in registro.assessment.issues}
        assert IssueCode.UNRESOLVED_FUSION_CONFLICT in codigos
        assert registro.eligibility is BuildEligibility.INELIGIBLE

    def test_conflito_de_formacao_nao_reprova_e_marca_a_familia(self) -> None:
        """§46. O placar concorda; a ESCALAÇÃO é que ficou indecidível — e é
        a política de build que decide o que fazer com ela."""
        registro = _avaliar(formacao_em_conflito())
        assert registro.eligibility is BuildEligibility.ELIGIBLE
        assert registro.families_in_conflict == (CoverageFamily.LINEUP,)
        assert IssueCode.UNRESOLVED_FUSION_CONFLICT not in {
            p.code for p in registro.assessment.issues
        }

    def test_identidade_fraca_por_TIPO_vai_para_revisao(self) -> None:
        """§13. CADA TIPO CONTRA O PISO DELE, e não contra uma média.

        `TEAM` em 0,91 passa no piso do EIXO de identidade (0,90) e reprova no
        piso do TIPO (0,92) — e é exatamente esse intervalo que uma média
        apagaria: com competição, temporada e partida em 1,0, a média daria
        0,977 e ninguém veria o time.
        """
        registro = _avaliar(
            cenario_publico_com_odds(),
            confidences={**CONFIANCAS_BOAS, SubjectType.TEAM: 0.91},
        )
        assert registro.eligibility is BuildEligibility.REVIEW_REQUIRED
        assert "TEAM" in (registro.assessment.reason or "")

    def test_identidade_muito_baixa_reprova_pelo_eixo_critico(self) -> None:
        """Abaixo do piso do EIXO, a guarda mais grave dispara primeiro — e é
        a ordem certa: o operador lê a causa raiz, não o sintoma."""
        registro = _avaliar(
            cenario_publico_com_odds(),
            confidences={**CONFIANCAS_BOAS, SubjectType.MATCH: 0.50},
        )
        assert registro.eligibility is BuildEligibility.INELIGIBLE
        assert "IDENTITY_CONFIDENCE" in (registro.assessment.reason or "")

    def test_identidade_obrigatoria_ausente_e_bloqueante(self) -> None:
        """Sem `SeasonId` não existe partida canônica."""
        parcial: dict[SubjectType, float] = {
            k: v for k, v in CONFIANCAS_BOAS.items() if k is not SubjectType.SEASON
        }
        registro = _avaliar(cenario_publico_com_odds(), confidences=parcial)
        assert registro.eligibility is BuildEligibility.INELIGIBLE
        assert IssueCode.MISSING_REQUIRED_IDENTITY in {
            p.code for p in registro.assessment.issues
        }

    def test_o_vetor_e_medido_e_nao_arbitrado(self) -> None:
        """Cada eixo sai de uma contagem sobre o candidato — a fração de
        campos sem conflito, a de contribuições com procedência."""
        vetor = _avaliar(cenario_publico_com_odds()).assessment.quality
        assert vetor.consistency == pytest.approx(1.0)
        assert vetor.provenance_quality == pytest.approx(1.0)
        assert vetor.identity_confidence == pytest.approx(0.98)

    def test_o_grupo_de_fusao_viaja_para_a_linhagem(self) -> None:
        """§47, §48: sem ele a linhagem para trás se rompe no primeiro elo."""
        cena = cenario_publico_com_odds()
        registro = _avaliar(cena)
        assert registro.fusion_group_id == cena.candidate.group_id
        assert registro.fusion_group_id == cena.group.id

    def test_sem_odds_a_familia_sai_nao_declarada(self) -> None:
        cobertura = _avaliar(sem_odds()).assessment.coverage
        odds = cobertura.of_family(CoverageFamily.ODDS)
        assert odds is not None
        assert odds.state is CoverageState.NOT_DECLARED
        assert odds.available_count == 0

    def test_o_nucleo_declara_placar_E_horario(self) -> None:
        """A lista existe para ser conferida por quem lê, e não deduzida.

        `KICKOFF` ESTÁ NO NÚCLEO E NÃO NO PLACAR (PR-04.2.1 §12): ele é fato
        sobre a partida — duas fontes com 20:00 e 23:00 discordam de verdade —
        e não faz parte do resultado, que é só o placar.
        """
        assert {p.value for p in SCORE_ROLES} == {"HOME_SCORE", "AWAY_SCORE"}
        assert {p.value for p in CORE_ROLES} == {
            "HOME_SCORE",
            "AWAY_SCORE",
            "KICKOFF",
        }


# ================================================ o caso de uso ====


def _caso(
    *, fusion: FakeFusionRunRepository, policy: HistoricalQualityPolicy | None = None
) -> tuple[
    RunHistoricalQualityAssessment, FakeQualityRunRepository, FakeQualityAssessmentRepository
]:
    execucoes = FakeQualityRunRepository()
    avaliacoes = FakeQualityAssessmentRepository()
    caso = RunHistoricalQualityAssessment(
        fusion_runs=fusion,
        quality_runs=execucoes,
        assessments=avaliacoes,
        clock=FrozenClock(AGORA),
        audit=FakeAudit(),
        policy=policy or DEFAULT_QUALITY_POLICY,
    )
    return caso, execucoes, avaliacoes


class TestRunHistoricalQualityAssessment:
    async def test_avalia_grava_e_conclui(self) -> None:
        fusao = fusion_run_concluida()
        caso, execucoes, avaliacoes = _caso(fusion=FakeFusionRunRepository(fusao))
        cena = cenario_publico_com_odds()

        saida = await caso.execute(
            actor=ATOR,
            fusion_run_ids=[fusao.id],
            batches=um_lote([cena.evidence()]),
        )

        assert saida.run.status is RunStatus.COMPLETED
        assert saida.run.counts.records_examined == 1
        assert saida.run.counts.eligible == 1
        assert saida.persisted == 1
        assert execucoes.runs[saida.run.id].status is RunStatus.COMPLETED
        assert len(avaliacoes.records) == 1

    async def test_a_impressao_da_saida_e_deterministica(self) -> None:
        """§53. Mesma entrada e mesma política produzem a mesma impressão —
        mesmo com ids de execução e de veredito diferentes."""
        fusao = fusion_run_concluida()
        cenas = cenarios(3)

        impressoes = []
        for _ in range(2):
            caso, _, _ = _caso(fusion=FakeFusionRunRepository(fusao))
            saida = await caso.execute(
                actor=ATOR,
                fusion_run_ids=[fusao.id],
                batches=um_lote([c.evidence() for c in cenas]),
            )
            impressoes.append(saida.run.output_fingerprint)

        assert impressoes[0] is not None
        assert impressoes[0] == impressoes[1]

    async def test_a_ordem_dos_lotes_nao_muda_a_impressao(self) -> None:
        """Duas execuções que processem os mesmos candidatos em lotes
        diferentes precisam produzir a mesma impressão, senão ela não prova
        reprodutibilidade nenhuma."""
        fusao = fusion_run_concluida()
        cenas = cenarios(4)
        evidencias = [c.evidence() for c in cenas]

        caso_a, _, _ = _caso(fusion=FakeFusionRunRepository(fusao))
        uma_vez = await caso_a.execute(
            actor=ATOR, fusion_run_ids=[fusao.id], batches=um_lote(evidencias)
        )
        caso_b, _, _ = _caso(fusion=FakeFusionRunRepository(fusao))
        aos_pares = await caso_b.execute(
            actor=ATOR,
            fusion_run_ids=[fusao.id],
            batches=lotes(evidencias[:2], evidencias[2:]),
        )
        assert uma_vez.run.output_fingerprint == aos_pares.run.output_fingerprint

    async def test_recusa_avaliar_sobre_fusao_que_falhou(self) -> None:
        """§8. Ela pode ter processado metade dos grupos."""
        falha = FusionRun.start(
            input_resolution_run_ids=("11111111-1111-4111-8111-111111111111",),
            policy_version=CURRENT_FUSION_POLICY_VERSION,
            at=AGORA,
            triggered_by=ATOR,
        ).fail(reason="worker morto", at=AGORA)
        caso, _, _ = _caso(fusion=FakeFusionRunRepository(falha))

        with pytest.raises(ConflictError, match="não produziu saída utilizável"):
            await caso.execute(
                actor=ATOR,
                fusion_run_ids=[falha.id],
                batches=um_lote([cenario_publico_com_odds().evidence()]),
            )

    async def test_fusao_inexistente_e_erro_de_nao_encontrado(self) -> None:
        caso, _, _ = _caso(fusion=FakeFusionRunRepository())
        with pytest.raises(NotFoundError):
            await caso.execute(
                actor=ATOR,
                fusion_run_ids=["fusao-fantasma"],
                batches=um_lote([]),
            )

    async def test_falha_no_meio_nao_declara_sucesso(self) -> None:
        """§100. Nenhuma declaração falsa: a execução termina em FAILED."""
        fusao = fusion_run_concluida()
        caso, execucoes, _ = _caso(fusion=FakeFusionRunRepository(fusao))

        async def explode() -> AsyncIterator[Sequence[CandidateEvidence]]:
            yield [cenario_publico_com_odds(0).evidence()]
            raise RuntimeError("terceiro lote quebrou")

        with pytest.raises(RuntimeError):
            await caso.execute(
                actor=ATOR, fusion_run_ids=[fusao.id], batches=explode()
            )

        gravada = next(iter(execucoes.runs.values()))
        assert gravada.status is RunStatus.FAILED
        assert gravada.output_fingerprint is None

    async def test_reprocessar_sob_politica_nova_preserva_a_anterior(self) -> None:
        """§52 e §99. Política 1.1 sobre a MESMA fusão produz execução NOVA;
        a de 1.0 fica exatamente como estava."""
        fusao = fusion_run_concluida()
        execucoes = FakeQualityRunRepository()
        avaliacoes = FakeQualityAssessmentRepository()
        cena = cenario_publico_com_odds()

        exigente = HistoricalQualityPolicy(
            version=PolicyVersion(major=1, minor=1),
            severities=dict(DEFAULT_QUALITY_POLICY.severities),
            critical_dimensions=DEFAULT_QUALITY_POLICY.critical_dimensions,
            minimums=dict(DEFAULT_QUALITY_POLICY.minimums),
            identity_minimums={
                **DEFAULT_QUALITY_POLICY.identity_minimums,
                SubjectType.MATCH: 0.999,
            },
            commercially_droppable=DEFAULT_QUALITY_POLICY.commercially_droppable,
        )

        primeiro = await RunHistoricalQualityAssessment(
            fusion_runs=FakeFusionRunRepository(fusao),
            quality_runs=execucoes,
            assessments=avaliacoes,
            clock=FrozenClock(AGORA),
            audit=FakeAudit(),
            policy=DEFAULT_QUALITY_POLICY,
        ).execute(
            actor=ATOR, fusion_run_ids=[fusao.id], batches=um_lote([cena.evidence()])
        )
        segundo = await RunHistoricalQualityAssessment(
            fusion_runs=FakeFusionRunRepository(fusao),
            quality_runs=execucoes,
            assessments=avaliacoes,
            clock=FrozenClock(AGORA),
            audit=FakeAudit(),
            policy=exigente,
        ).execute(
            actor=ATOR, fusion_run_ids=[fusao.id], batches=um_lote([cena.evidence()])
        )

        assert primeiro.run.id != segundo.run.id
        assert execucoes.runs[primeiro.run.id].policy_version == PolicyVersion(1, 0)
        assert execucoes.runs[primeiro.run.id].counts.eligible == 1
        # A execução ANTERIOR continua dizendo o que dizia.
        assert execucoes.runs[segundo.run.id].counts.review_required == 1
        assert len(avaliacoes.records) == 2

    def test_o_ator_e_um_servico_nomeado_e_nunca_system(self) -> None:
        """§75. `system` numa trilha significa «não sabemos quem»."""
        assert QUALITY_ASSESSOR == "historical-quality-assessor"
        assert Actor.service(QUALITY_ASSESSOR).is_service

    async def test_a_trilha_registra_inicio_e_fim_e_nao_cada_partida(self) -> None:
        """§76. O volume da trilha não pode ser governado pelo tamanho do
        corpus, senão ninguém acha as decisões no meio."""
        fusao = fusion_run_concluida()
        trilha = FakeAudit()
        caso = RunHistoricalQualityAssessment(
            fusion_runs=FakeFusionRunRepository(fusao),
            quality_runs=FakeQualityRunRepository(),
            assessments=FakeQualityAssessmentRepository(),
            clock=FrozenClock(AGORA),
            audit=trilha,
        )
        await caso.execute(
            actor=ATOR,
            fusion_run_ids=[fusao.id],
            batches=um_lote([c.evidence() for c in cenarios(5)]),
        )
        assert trilha.actions() == ["QUALITY_RUN_STARTED", "QUALITY_RUN_COMPLETED"]


class TestConsultas:
    async def test_get_quality_run(self) -> None:
        fusao = fusion_run_concluida()
        caso, execucoes, _ = _caso(fusion=FakeFusionRunRepository(fusao))
        saida = await caso.execute(
            actor=ATOR,
            fusion_run_ids=[fusao.id],
            batches=um_lote([cenario_publico_com_odds().evidence()]),
        )
        lida = await GetQualityRun(quality_runs=execucoes).execute(saida.run.id)
        assert lida.id == saida.run.id

        with pytest.raises(NotFoundError):
            await GetQualityRun(quality_runs=execucoes).execute("nao-existe")

    async def test_listar_filtra_no_repositorio(self) -> None:
        fusao = fusion_run_concluida()
        caso, execucoes, avaliacoes = _caso(fusion=FakeFusionRunRepository(fusao))
        saida = await caso.execute(
            actor=ATOR,
            fusion_run_ids=[fusao.id],
            batches=um_lote(
                [
                    cenario_publico_com_odds(0).evidence(),
                    placar_em_conflito(1).evidence(),
                ]
            ),
        )
        listar = ListQualityAssessments(
            quality_runs=execucoes, assessments=avaliacoes
        )
        elegiveis, total_elegiveis = await listar.execute(
            saida.run.id, eligibility=BuildEligibility.ELIGIBLE
        )
        todos, total = await listar.execute(saida.run.id)
        assert total_elegiveis == 1
        assert total == 2
        assert len(elegiveis) == 1
        assert len(todos) == 2
