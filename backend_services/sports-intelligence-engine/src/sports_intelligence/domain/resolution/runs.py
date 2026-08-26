"""A execução de resolução — e por que ela é uma entidade, não um log.

POR QUE `ResolutionRun` EXISTE E NÃO ESTENDE `DatasetLifecycle`. O ciclo de
vida do dataset foi deliberadamente encerrado em `STAGED` no PR-02: ele
descreve o que aconteceu com os BYTES. Resolução e fusão são PROCESSOS sobre
esses bytes, e o mesmo dataset pode passar por cinco execuções de resolução
com cinco versões de resolver diferentes — todas válidas, todas coexistindo.

Enfiar `RESOLVING`, `RESOLVED`, `FUSING`, `FUSED` no `DatasetLifecycle` faria
o dataset ter um estado só, e a quinta execução apagaria o registro das
quatro anteriores. Pior: faria um estado de processo parecer um estado de
evidência, e a evidência não muda quando o processo roda de novo.

UMA EXECUÇÃO CONCLUÍDA É IMUTÁVEL (ADR-0019). Política nova produz execução
nova; a anterior fica como estava, e a diferença entre as duas é o que mostra
o que o resolver novo passou a enxergar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.datasets.content import ContentHash
from sports_intelligence.domain.resolution.decisions import DecisionCounts, DecisionVersions
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import DatasetVersion


class RunStatus(StrEnum):
    """Onde a execução está. Fechado, e compartilhado com a fusão.

    UM ENUM PARA OS DOIS TIPOS DE EXECUÇÃO porque os estados são os mesmos e
    duplicá-los produziria dois enums idênticos que divergem no dia em que
    alguém acrescenta um estado a um só.
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    #: Terminou e produziu itens que exigem decisão humana. Distinto de
    #: `COMPLETED` porque a ação é outra: alguém precisa abrir a fila.
    COMPLETED_WITH_REVIEW = "COMPLETED_WITH_REVIEW"
    #: Falha NOSSA — banco fora, worker morto, arquivo ilegível. Distinto de
    #: uma execução que terminou com muitos não resolvidos: ali os dados são
    #: ruins, aqui nós é que falhamos.
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in (
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_REVIEW,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        )

    @property
    def produced_usable_output(self) -> bool:
        """Se a saída desta execução pode alimentar a fusão.

        `COMPLETED_WITH_REVIEW` PODE. Os registros que resolveram são
        utilizáveis; os que foram para a fila simplesmente não entram em
        grupo nenhum. Bloquear a execução inteira por causa de dez registros
        ambíguos em cem mil pararia o pipeline pelo motivo errado.
        """
        return self in (RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_REVIEW)


#: O grafo, escrito por extenso. Regra derivada permitiria uma aresta nova
#: aparecer sem ninguém decidi-la.
_TRANSICOES: Final[dict[RunStatus, frozenset[RunStatus]]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.COMPLETED_WITH_REVIEW,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.COMPLETED_WITH_REVIEW: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in _TRANSICOES[current]


@final
@dataclass(frozen=True, slots=True)
class ResolutionRun:
    """Uma execução de resolução sobre um dataset, sob versões declaradas."""

    id: str
    dataset_id: DatasetId
    dataset_version: DatasetVersion
    #: A IMPRESSÃO DO MANIFESTO É O QUE FECHA A LINHAGEM. Sem ela, «esta
    #: execução rodou sobre o dataset X» é uma afirmação sobre um dataset que
    #: pode ter mudado desde então.
    manifest_fingerprint: ContentHash
    versions: DecisionVersions
    status: RunStatus
    started_at: Instant
    triggered_by: Actor
    counts: DecisionCounts = field(default_factory=DecisionCounts)
    completed_at: Instant | None = None
    #: Preenchido só em `FAILED`, com o tipo da falha — nunca com o traceback
    #: nem com conteúdo do dataset.
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status.is_terminal and self.completed_at is None:
            raise ValidationError(f"execução em {self.status} sem instante de conclusão")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValidationError("execução concluída antes de começar")
        if self.status is RunStatus.FAILED and not (self.failure_reason or "").strip():
            raise ValidationError(
                "execução FAILED sem motivo: sem ele a investigação começa do zero"
            )
        self.counts.assert_consistent()

    @classmethod
    def start(
        cls,
        *,
        dataset_id: DatasetId,
        dataset_version: DatasetVersion,
        manifest_fingerprint: ContentHash,
        versions: DecisionVersions,
        at: Instant,
        triggered_by: Actor,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            manifest_fingerprint=manifest_fingerprint,
            versions=versions,
            status=RunStatus.RUNNING,
            started_at=at,
            triggered_by=triggered_by,
        )

    def complete(self, *, counts: DecisionCounts, at: Instant) -> Self:
        """Fecha a execução. O status sai das CONTAGENS, não de um parâmetro.

        Derivá-lo é o que impede uma execução com trezentos itens na fila de
        revisão ser marcada `COMPLETED` por engano — e `COMPLETED` é o que os
        painéis leem como «nada a fazer».
        """
        self._assert_can_finish()
        counts.assert_consistent()
        destino = RunStatus.COMPLETED_WITH_REVIEW if counts.needs_human > 0 else RunStatus.COMPLETED
        return replace(self, status=destino, counts=counts, completed_at=at)

    def fail(self, *, reason: str, at: Instant) -> Self:
        self._assert_can_finish()
        return replace(
            self,
            status=RunStatus.FAILED,
            completed_at=at,
            failure_reason=reason[:500],
        )

    def _assert_can_finish(self) -> None:
        if self.status.is_terminal:
            raise ConflictError(
                f"execução já terminou em {self.status} — uma execução concluída é "
                "imutável; reprocessar produz outra (ADR-0019)",
                context={"run_id": self.id, "status": self.status.value},
            )

    @property
    def duration_seconds(self) -> float | None:
        """`None` enquanto não terminou. Nunca zero: uma execução em curso
        não tem duração, e informar zero faria um painel mostrar
        instantâneo o que está rodando há uma hora."""
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def records_per_second(self) -> float | None:
        duracao = self.duration_seconds
        if duracao is None or duracao <= 0 or self.counts.total == 0:
            return None
        return self.counts.total / duracao

    def __str__(self) -> str:
        return (
            f"resolução {self.id[:8]} [{self.status}] {self.versions} · "
            f"{self.counts.resolved}/{self.counts.total} resolvidos"
        )


def assert_not_historical_active(run: ResolutionRun) -> None:
    """A guarda do limite deste PR, escrita como função executável.

    Ela SEMPRE recusa. Existe para ser chamada por qualquer caminho futuro
    que pretenda promover a saída de uma resolução — ou de uma fusão — para o
    índice histórico. Entre uma coisa e outra estão o PR-04 inteiro (qualidade
    e construção canônica) e a barreira do ADR-0007.
    """
    from sports_intelligence.domain.shared.errors import InvariantViolationError

    raise InvariantViolationError(
        f"a saída da execução {run.id} é um CANDIDATO canônico, não conhecimento "
        "histórico ativo. A promoção exige avaliação de qualidade e construção "
        "canônica, que são o PR-04 (ADR-0007, ADR-0016).",
        context={"run_id": run.id, "status": run.status.value},
    )
