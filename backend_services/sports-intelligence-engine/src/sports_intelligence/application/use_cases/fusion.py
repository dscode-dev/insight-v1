"""Os casos de uso de fusão — só sobre identidade já provada.

A PRÉ-CONDIÇÃO É O ASSUNTO (ADR-0022). `RunFusion` lê as decisões `RESOLVED`
das execuções de resolução declaradas como entrada, e monta
`ResolvedSourceRecord` a partir delas. Um registro sem decisão não tem como
entrar: o tipo não se constrói sem `resolution_decision_id`.

Se não for possível PROVAR que duas linhas pertencem à mesma partida, elas não
são fundidas. Ficam como estão, cada uma na sua fonte, e a execução reporta
quantas ficaram de fora.

UMA EXECUÇÃO CONCLUÍDA É IMUTÁVEL (ADR-0020). Política nova produz execução
nova; a anterior fica exatamente como estava. Comparar as duas é o único jeito
honesto de medir o que a política nova mudou.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.events.envelope import EventEnvelope
from sports_intelligence.domain.events.envelope_types import (
    DOMAIN_SCHEMA,
    FUSION_CONFLICT_DETECTED,
    FUSION_RUN_COMPLETED,
)
from sports_intelligence.domain.fusion.models import ResolvedSourceRecord
from sports_intelligence.domain.fusion.policy import DEFAULT_FUSION_POLICY, FusionPolicy
from sports_intelligence.domain.fusion.runs import (
    FusedMatchCandidate,
    FusionRun,
    assert_not_historical_active,
)
from sports_intelligence.domain.resolution.decisions import SubjectType
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.errors import ConflictError, NotFoundError
from sports_intelligence.ingestion.fusion.engine import (
    FusionEngine,
    count_fusion,
    group_by_identity,
)
from sports_intelligence.ports.audit import AuditPort
from sports_intelligence.ports.clock import ClockPort
from sports_intelligence.ports.event_bus import EventPublisherPort
from sports_intelligence.ports.repositories.resolution import (
    FusionRunRepositoryPort,
    ResolutionDecisionRepositoryPort,
    ResolutionRunRepositoryPort,
)

#: O ator de serviço da fusão. Identificado pelo que ele É (§11).
FUSION_WORKER: Final[str] = "historical-fusion-worker"


@final
@dataclass(frozen=True, slots=True)
class FusionOutput:
    run: FusionRun
    candidates: tuple[FusedMatchCandidate, ...]
    #: Registros que não entraram em grupo nenhum — duplicata interna de uma
    #: fonte. Reportados porque sumir em silêncio esconderia um defeito da
    #: fonte que alguém precisa ver.
    discarded: int


@final
@dataclass(frozen=True, slots=True)
class RunFusion:
    """Agrupa por identidade provada e funde campo a campo."""

    resolution_runs: ResolutionRunRepositoryPort
    decisions: ResolutionDecisionRepositoryPort
    fusion_runs: FusionRunRepositoryPort
    clock: ClockPort
    audit: AuditPort
    publisher: EventPublisherPort
    policy: FusionPolicy = DEFAULT_FUSION_POLICY

    async def execute(
        self,
        *,
        actor: Actor,
        resolution_run_ids: Sequence[str],
        records: Sequence[ResolvedSourceRecord],
        correlation_id: str | None = None,
    ) -> FusionOutput:
        await self._validar_entradas(resolution_run_ids)

        execucao = await self.fusion_runs.create(
            FusionRun.start(
                input_resolution_run_ids=tuple(resolution_run_ids),
                policy_version=self.policy.version,
                at=self.clock.now(),
                triggered_by=actor,
            )
        )
        try:
            grupos, descartados = group_by_identity(tuple(records))
            motor = FusionEngine(self.policy)
            candidatos = tuple(motor.fuse(grupo) for grupo in grupos)
            contagens = count_fusion(candidatos, grupos)

            await self.fusion_runs.save_groups(execucao.id, grupos)
            await self.fusion_runs.save_candidates(execucao.id, candidatos)
        except Exception as erro:
            falha = execucao.fail(reason=type(erro).__name__, at=self.clock.now())
            await self.fusion_runs.finish(falha)
            raise

        concluida = execucao.complete(
            counts=contagens,
            at=self.clock.now(),
            output_fingerprint=_impressao_do_conjunto(candidatos),
        )
        await self.fusion_runs.finish(concluida)
        await self._publicar(concluida, candidatos, correlation_id)
        await self.audit.record(
            AuditEntry.of(
                AuditAction.DATASET_VALIDATION_COMPLETED,
                actor=actor,
                at=self.clock.now(),
                correlation_id=correlation_id,
                fusion_run=concluida.id,
                groups=contagens.groups,
                conflicts=contagens.unresolved_conflicts,
            )
        )
        return FusionOutput(
            run=concluida, candidates=candidatos, discarded=len(descartados)
        )

    async def _validar_entradas(self, ids: Sequence[str]) -> None:
        """Recusa fundir a partir de execuções que não produziram saída útil.

        UMA EXECUÇÃO `FAILED` NÃO SERVE. Ela pode ter processado metade do
        dataset, e fundir sobre metade produziria um candidato que parece
        completo e não é.
        """
        if not ids:
            raise ConflictError("fusão sem execução de resolução de entrada")
        for run_id in ids:
            execucao = await self.resolution_runs.by_id(run_id)
            if execucao is None:
                raise NotFoundError(f"execução de resolução {run_id} não encontrada")
            if not execucao.status.produced_usable_output:
                raise ConflictError(
                    f"a execução {run_id} terminou em {execucao.status} e não produziu "
                    "saída utilizável — fundir sobre ela daria um candidato que "
                    "parece completo e não é",
                    context={"run_id": run_id, "status": execucao.status.value},
                )

    async def _publicar(
        self,
        run: FusionRun,
        candidates: tuple[FusedMatchCandidate, ...],
        correlation_id: str | None,
    ) -> None:
        agora = self.clock.now()
        await self.publisher.publish(
            EventEnvelope.create(
                event_type=FUSION_RUN_COMPLETED,
                schema_version=DOMAIN_SCHEMA,
                occurred_at=run.completed_at or agora,
                produced_at=agora,
                payload={
                    "run_id": run.id,
                    "policy_version": str(run.policy_version),
                    "groups": run.counts.groups,
                    "candidates": len(candidates),
                    "conflicts": run.counts.conflicts,
                    "unresolved_conflicts": run.counts.unresolved_conflicts,
                    "output_fingerprint": run.output_fingerprint.value
                    if run.output_fingerprint
                    else None,
                    "correlation_id": correlation_id,
                    # DITO EXPLICITAMENTE. O candidato fundido não é
                    # conhecimento histórico ativo: falta a avaliação de
                    # qualidade e a construção canônica, que são o PR-04.
                    "historical_active": False,
                },
            )
        )
        if run.counts.unresolved_conflicts:
            await self.publisher.publish(
                EventEnvelope.create(
                    event_type=FUSION_CONFLICT_DETECTED,
                    schema_version=DOMAIN_SCHEMA,
                    occurred_at=agora,
                    produced_at=agora,
                    payload={
                        "run_id": run.id,
                        "unresolved": run.counts.unresolved_conflicts,
                        "affected_matches": sum(
                            1 for c in candidates if c.has_unresolved_conflict
                        ),
                    },
                )
            )


@final
@dataclass(frozen=True, slots=True)
class BuildResolvedRecords:
    """Monta `ResolvedSourceRecord` a partir das decisões de uma execução.

    É A PORTA ENTRE RESOLUÇÃO E FUSÃO, e ela só deixa passar `RESOLVED`. Um
    registro cuja partida ficou `AMBIGUOUS` simplesmente não aparece na saída
    — e o chamador vê a diferença entre o número de registros lidos e o
    número que passou.
    """

    decisions: ResolutionDecisionRepositoryPort

    async def execute(
        self, *, run_id: str, records: Sequence[ResolvedSourceRecord]
    ) -> tuple[ResolvedSourceRecord, ...]:
        resolvidos = await self.decisions.resolved_entities_of_run(
            run_id, SubjectType.MATCH
        )
        return tuple(r for r in records if str(r.record_ref) in resolvidos)


@final
@dataclass(frozen=True, slots=True)
class GetFusionRun:
    fusion_runs: FusionRunRepositoryPort

    async def execute(self, run_id: str) -> FusionRun:
        execucao = await self.fusion_runs.by_id(run_id)
        if execucao is None:
            raise NotFoundError(f"execução de fusão {run_id} não encontrada")
        return execucao


@final
@dataclass(frozen=True, slots=True)
class ListFusionConflicts:
    """Os conflitos não resolvidos de uma execução, para o operador.

    MÉTODO PRÓPRIO NO REPOSITÓRIO, e não filtro em Python: carregar todos os
    candidatos para mostrar dez linhas traria megabytes.
    """

    fusion_runs: FusionRunRepositoryPort

    async def execute(
        self, run_id: str, *, limit: int = 100
    ) -> Sequence[tuple[str, str, str]]:
        if await self.fusion_runs.by_id(run_id) is None:
            raise NotFoundError(f"execução de fusão {run_id} não encontrada")
        return await self.fusion_runs.conflicts_of(run_id, limit=limit)


def _impressao_do_conjunto(candidates: tuple[FusedMatchCandidate, ...]) -> ContentHash | None:
    """A impressão do conjunto inteiro de saída.

    ORDENADA PELO ID DA PARTIDA, e não pela ordem de processamento: duas
    execuções que processam os mesmos grupos em ordens diferentes precisam
    produzir a mesma impressão, senão ela não prova reprodutibilidade (§92).
    """
    if not candidates:
        return None
    digest = hashlib.sha256()
    for candidato in sorted(candidates, key=lambda c: str(c.canonical_match_id)):
        digest.update(candidato.fingerprint.value.encode())
    return ContentHash(digest.hexdigest())


def assert_output_is_not_historical(candidate: FusedMatchCandidate) -> None:
    """Reexporta a guarda do limite, para quem consumir a saída.

    Ela SEMPRE recusa. Está aqui para que o PR-04 — ou qualquer caminho que
    tente promover um candidato — encontre a recusa no lugar onde iria
    procurar.
    """
    assert_not_historical_active(candidate)
