"""Os casos de uso da avaliação histórica de qualidade.

A PRÉ-CONDIÇÃO É A MESMA DISCIPLINA DO PR-03 (ADR-0022, agora ADR-0023): a
avaliação só consome FUSÕES CONCLUÍDAS. Uma execução de fusão em curso pode
ter processado metade dos grupos, e avaliar metade produziria um veredito que
parece completo e não é (§8).

O CASO DE USO É PURO SOBRE LOTES. Ele recebe um iterador assíncrono de
evidências — quem lê o object store, remonta candidatos e carrega decisões é a
BORDA, como no PR-03. Com a leitura aqui dentro, avaliar qualidade exigiria um
object store configurado, e o caso de uso deixaria de ser testável sem
infraestrutura.

NADA AQUI MATERIALIZA A EXECUÇÃO INTEIRA (§67, §79). As contagens são
acumuladas lote a lote e a impressão determinística é construída
incrementalmente — um `list(assessments)` de dez mil vereditos com vetor,
cobertura, licenças e problemas é exatamente o pico de memória que o PR-03.2
mediu e corrigiu.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.quality.assessment import BuildEligibility
from sports_intelligence.domain.quality.policy import (
    DEFAULT_QUALITY_POLICY,
    HistoricalQualityPolicy,
)
from sports_intelligence.domain.quality.runs import (
    MatchQualityRecord,
    QualityCounts,
    QualityRun,
    QualityRunInput,
)
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.historical.quality.assessor import (
    CandidateEvidence,
    HistoricalQualityAssessor,
)
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.repositories.quality import (
    QualityAssessmentRepositoryPort,
    QualityRunRepositoryPort,
)
from sports_intelligence.ports.repositories.resolution import FusionRunRepositoryPort


@final
@dataclass(frozen=True, slots=True)
class QualityOutput:
    run: QualityRun
    #: Quantos vereditos de fato entraram no banco. DIFERENTE de
    #: `run.counts.records_examined` quando um lote foi reexecutado: a
    #: diferença é informação, e escondê-la faria uma reexecução parcial
    #: parecer uma execução completa.
    persisted: int


@final
@dataclass(frozen=True, slots=True)
class RunHistoricalQualityAssessment:
    """Avalia os candidatos de fusões concluídas, sob uma política versionada."""

    fusion_runs: FusionRunRepositoryPort
    quality_runs: QualityRunRepositoryPort
    assessments: QualityAssessmentRepositoryPort
    clock: ClockPort
    audit: AuditPort
    policy: HistoricalQualityPolicy = DEFAULT_QUALITY_POLICY

    async def execute(
        self,
        *,
        actor: Actor,
        fusion_run_ids: Sequence[str],
        batches: AsyncIterator[Sequence[CandidateEvidence]],
        correlation_id: str | None = None,
    ) -> QualityOutput:
        entradas = await self._validar_entradas(fusion_run_ids)

        execucao = await self.quality_runs.create(
            QualityRun.start(
                inputs=entradas,
                policy_version=self.policy.version,
                policy_fingerprint=policy_fingerprint(self.policy),
                at=self.clock.now(),
                triggered_by=actor,
            )
        )
        await self._snapshot(execucao)
        await self._auditar(
            AuditAction.QUALITY_RUN_STARTED,
            actor=actor,
            correlation_id=correlation_id,
            quality_run=execucao.id,
            policy_version=str(self.policy.version),
        )

        avaliador = HistoricalQualityAssessor(policy=self.policy)
        contagens = QualityCounts()
        gravados = 0
        impressao = hashlib.sha256()
        try:
            async for lote in batches:
                registros = tuple(
                    avaliador.assess(evidencia, quality_run_id=execucao.id)
                    for evidencia in lote
                )
                gravados += await self.assessments.append_many(
                    registros, policy=self.policy
                )
                contagens = contagens.merged_with(
                    QualityCounts.of(tuple(r.assessment for r in registros))
                )
                _acumular(impressao, registros)
        except Exception as erro:
            falha = execucao.fail(reason=type(erro).__name__, at=self.clock.now())
            await self.quality_runs.finish(falha)
            raise

        concluida = execucao.complete(
            counts=contagens,
            at=self.clock.now(),
            output_fingerprint=ContentHash(impressao.hexdigest()),
        )
        await self.quality_runs.finish(concluida)
        await self._auditar(
            AuditAction.QUALITY_RUN_COMPLETED,
            actor=actor,
            correlation_id=correlation_id,
            quality_run=concluida.id,
            status=concluida.status.value,
            examined=contagens.records_examined,
            eligible=contagens.eligible,
            review_required=contagens.review_required,
            ineligible=contagens.ineligible,
        )
        return QualityOutput(run=concluida, persisted=gravados)

    async def _validar_entradas(
        self, run_ids: Sequence[str]
    ) -> tuple[QualityRunInput, ...]:
        """Recusa avaliar sobre fusões que não produziram saída utilizável.

        E CARREGA A IMPRESSÃO DE CADA UMA. Sem ela, «esta avaliação rodou sobre
        a fusão X» é uma afirmação sobre uma fusão que pode ter sido
        reexecutada desde então — e a reprodutibilidade do §52 se apoia
        justamente em conseguir provar que a entrada era a mesma.
        """
        if not run_ids:
            raise ConflictError("avaliação sem execução de fusão de entrada")
        entradas: list[QualityRunInput] = []
        for run_id in run_ids:
            execucao = await self.fusion_runs.by_id(run_id)
            if execucao is None:
                raise NotFoundError(f"execução de fusão {run_id} não encontrada")
            if not execucao.status.produced_usable_output:
                raise ConflictError(
                    f"a execução de fusão {run_id} terminou em {execucao.status} e não "
                    "produziu saída utilizável — avaliar sobre ela daria um veredito "
                    "sobre metade dos grupos que pareceria completo",
                    context={"run_id": run_id, "status": execucao.status.value},
                )
            entradas.append(
                QualityRunInput(
                    fusion_run_id=run_id,
                    fusion_output_fingerprint=execucao.output_fingerprint,
                )
            )
        return tuple(entradas)

    async def _snapshot(self, run: QualityRun) -> None:
        """Grava a política inteira dentro da execução, quando o adapter o
        oferecer. O port não exige o método: um duplo em memória não precisa
        dele para provar comportamento, e exigi-lo poluiria o contrato."""
        gravar = getattr(self.quality_runs, "save_policy_snapshot", None)
        if gravar is not None:
            await gravar(run.id, self.policy)

    async def _auditar(
        self,
        action: AuditAction,
        *,
        actor: Actor,
        correlation_id: str | None,
        **detalhe: Any,
    ) -> None:
        await self.audit.record(
            AuditEntry.of(
                action,
                actor=actor,
                at=self.clock.now(),
                correlation_id=correlation_id,
                **detalhe,
            )
        )


@final
@dataclass(frozen=True, slots=True)
class GetQualityRun:
    quality_runs: QualityRunRepositoryPort

    async def execute(self, run_id: str) -> QualityRun:
        execucao = await self.quality_runs.by_id(run_id)
        if execucao is None:
            raise NotFoundError(f"execução de qualidade {run_id} não encontrada")
        return execucao


@final
@dataclass(frozen=True, slots=True)
class ListQualityAssessments:
    """Uma página de vereditos, para o operador e para os testes.

    O FILTRO VAI AO BANCO (§68). «Mostre as inelegíveis» sobre dez mil
    partidas não deveria carregar dez mil vereditos para descartar nove mil e
    oitocentos.
    """

    quality_runs: QualityRunRepositoryPort
    assessments: QualityAssessmentRepositoryPort

    async def execute(
        self,
        run_id: str,
        *,
        eligibility: BuildEligibility | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[MatchQualityRecord], int]:
        if await self.quality_runs.by_id(run_id) is None:
            raise NotFoundError(f"execução de qualidade {run_id} não encontrada")
        return await self.assessments.by_run(
            run_id, eligibility=eligibility, limit=limit, offset=offset
        )


def policy_fingerprint(policy: HistoricalQualityPolicy) -> ContentHash:
    """A impressão da política inteira.

    ELA PEGA O QUE A VERSÃO NÃO PEGA. Alguém edita um piso e esquece de subir
    o número: as duas execuções ficam rotuladas `1.0` e decidem diferente, e a
    pergunta «sob qual política esta partida reprovou» passa a ter duas
    respostas com o mesmo nome. Sessenta e quatro caracteres resolvem.
    """
    bruto = json.dumps(
        policy.as_canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return ContentHash(hashlib.sha256(bruto).hexdigest())


def _acumular(digest: Any, records: Sequence[MatchQualityRecord]) -> None:
    """Acrescenta um lote à impressão determinística do conjunto.

    ORDENADO PELO ID DA PARTIDA DENTRO DO LOTE, e os lotes chegam em ordem de
    partida. Duas execuções que processem os mesmos candidatos em ordens
    diferentes de lote produziriam impressões diferentes — e aí ela não
    provaria reprodutibilidade nenhuma (§53).

    O `id` DO VEREDITO E O DA EXECUÇÃO FICAM DE FORA (§54). Eles são UUID
    sorteado e mudam a cada execução; incluí-los faria a impressão dizer «são
    diferentes» sobre duas execuções idênticas.
    """
    for registro in sorted(records, key=lambda r: str(r.match_id)):
        digest.update(
            json.dumps(
                registro.as_canonical(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        )
