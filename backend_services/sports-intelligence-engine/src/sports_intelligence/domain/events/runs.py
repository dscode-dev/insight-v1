"""A EXECUÇÃO de canonicalização de eventos. Imutável quando termina.

O MESMO DESENHO DO `QualityRun` E DO `CanonicalBuildRun`, e a repetição é
deliberada: quem já entendeu um entende os três. Uma execução registra o que
consumiu, sob qual política, quando, por quem e com quantos eventos em cada
desfecho — e uma execução concluída NUNCA é atualizada.

    política nova   →   execução nova
    a anterior      →   fica exatamente como estava

Sem isso, «por que este evento não entrou» teria uma resposta que muda com o
tempo: a política seria relida no estado atual, e o veredito de ontem passaria
a ser explicado por uma regra que não existia ontem.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Self, final

from sports_intelligence.domain.events.build import EventBuildCounts
from sports_intelligence.domain.quality.licensing import UsageScope
from sports_intelligence.domain.resolution.runs import RunStatus
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import DatasetId, ProviderId
from sports_intelligence.domain.shared.temporal import Instant


@final
@dataclass(frozen=True, slots=True)
class CanonicalEventBuildRun:
    """Uma execução de canonicalização de eventos.

    ELA GUARDA A VERSÃO DA TABELA DE TIPOS, e não só a da política. As duas
    mudam por motivos diferentes: a política muda o que é elegível, a tabela
    muda o que é traduzível. Um evento que ontem foi `UNMAPPED_TYPE` e hoje
    entra mudou por causa da segunda, e sem o número não haveria como dizer
    isso sem reabrir os dois arquivos.
    """

    id: str
    dataset_id: DatasetId
    provider_id: ProviderId
    scope: UsageScope
    policy_version: int
    type_mapping_version: int
    status: RunStatus
    started_at: Instant
    triggered_by: Actor
    quality_run_id: str | None = None
    counts: EventBuildCounts = field(default_factory=EventBuildCounts)
    completed_at: Instant | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(
                f"execução em {self.status} sem instante de conclusão — a duração "
                "é a primeira coisa que se olha num incidente"
            )
        if self.status is RunStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError("execução FAILED sem motivo")
        if self.status.is_terminal:
            self.counts.assert_consistent()

    @classmethod
    def start(
        cls,
        *,
        dataset_id: DatasetId,
        provider_id: ProviderId,
        scope: UsageScope,
        policy_version: int,
        type_mapping_version: int,
        at: Instant,
        triggered_by: Actor,
        quality_run_id: str | None = None,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            provider_id=provider_id,
            scope=scope,
            policy_version=policy_version,
            type_mapping_version=type_mapping_version,
            status=RunStatus.RUNNING,
            started_at=at,
            triggered_by=triggered_by,
            quality_run_id=quality_run_id,
        )

    def complete(self, *, counts: EventBuildCounts, at: Instant) -> Self:
        """Fecha a execução. `COMPLETED_WITH_REVIEW` quando há pendência.

        O ESTADO DIZ QUE HÁ TRABALHO HUMANO ESPERANDO, e a distinção importa:
        `COMPLETED` faria alguém achar que acabou, e os eventos em revisão
        ficariam esperando por uma decisão que ninguém sabe que precisa tomar.
        """
        self._assert_em_curso()
        counts.assert_consistent()
        estado = (
            RunStatus.COMPLETED_WITH_REVIEW
            if counts.events_review_required
            else RunStatus.COMPLETED
        )
        return replace(self, status=estado, counts=counts, completed_at=at)

    def fail(self, *, reason: str, at: Instant) -> Self:
        self._assert_em_curso()
        return replace(
            self,
            status=RunStatus.FAILED,
            failure_reason=reason[:500],
            completed_at=at,
        )

    def _assert_em_curso(self) -> None:
        if self.status.is_terminal:
            raise ConflictError(
                f"a execução {self.id[:8]} já terminou em {self.status} e é "
                "imutável: política nova produz execução NOVA, e a anterior "
                "continua explicando os vereditos que ela produziu",
                context={"run_id": self.id, "status": self.status.value},
            )

    def __str__(self) -> str:
        return (
            f"canonicalização de eventos {self.id[:8]} [{self.status}] {self.scope} · {self.counts}"
        )
