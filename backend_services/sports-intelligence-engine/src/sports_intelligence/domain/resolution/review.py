"""A fila de revisão: onde o motor admite que não sabe.

ELA É A CONTRAPARTE DO CONSERVADORISMO. Uma política que prefere
`REVIEW_REQUIRED` a um merge duvidoso só funciona se existir para onde mandar
o duvidoso — senão a escolha conservadora vira, na prática, «esse dado
simplesmente some», e a pressão para afrouxar o limiar fica irresistível.

O QUE ESTA FILA NÃO É. Não é workflow. Não tem etapas, aprovação em dois
níveis, SLA nem escalonamento. Tem quatro estados e um dono opcional, porque
é isso que o problema exige hoje — e um motor de workflow construído antes do
segundo caso de uso é calibrado para um caso hipotético.

A DECISÃO HUMANA É EVIDÊNCIA, NÃO EXCEÇÃO. Resolver um item da fila produz um
`ResolutionDecision` completo, com método `MANUAL_REVIEW`, ator humano e
motivo — exatamente como uma decisão automática, sob as mesmas regras. Nunca
um `UPDATE` silencioso no mapeamento: um mapeamento que aparece sem decisão
que o explique é indistinguível de um mapeamento inventado.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Self, final

from sports_intelligence.domain.resolution.decisions import (
    ResolutionStatus,
    SourceValue,
    SubjectType,
)
from sports_intelligence.domain.resolution.evidence import ResolutionAlternative
from sports_intelligence.domain.shared.actor import Actor
from sports_intelligence.domain.shared.errors import ConflictError, ValidationError
from sports_intelligence.domain.shared.identity import EntityId, ProviderId
from sports_intelligence.domain.shared.temporal import Instant

MAX_REASON_LENGTH: Final[int] = 1000


class ReviewStatus(StrEnum):
    """Quatro estados. Nenhum a mais."""

    OPEN = "OPEN"
    #: Alguém pegou. Existe para que dois operadores não decidam o mesmo item
    #: em paralelo e produzam duas decisões conflitantes.
    IN_REVIEW = "IN_REVIEW"
    #: Um humano escolheu um candidato. Gerou decisão e mapeamento.
    RESOLVED = "RESOLVED"
    #: Um humano recusou todos os candidatos. TAMBÉM gera decisão — a de que
    #: este registro não corresponde a nenhuma entidade conhecida.
    REJECTED = "REJECTED"

    @property
    def is_open(self) -> bool:
        return self in (ReviewStatus.OPEN, ReviewStatus.IN_REVIEW)


_TRANSICOES: Final[dict[ReviewStatus, frozenset[ReviewStatus]]] = {
    ReviewStatus.OPEN: frozenset(
        {ReviewStatus.IN_REVIEW, ReviewStatus.RESOLVED, ReviewStatus.REJECTED}
    ),
    # Devolver à fila é legítimo: quem pegou percebeu que não sabe decidir.
    ReviewStatus.IN_REVIEW: frozenset(
        {ReviewStatus.RESOLVED, ReviewStatus.REJECTED, ReviewStatus.OPEN}
    ),
    ReviewStatus.RESOLVED: frozenset(),
    ReviewStatus.REJECTED: frozenset(),
}


@final
@dataclass(frozen=True, slots=True)
class ReviewSubject:
    """O que está em revisão, no mínimo necessário para decidir.

    NÃO CARREGA O REGISTRO INTEIRO. A referência ao registro de origem
    (dataset, arquivo, linha) permite buscá-lo quando alguém precisar; copiar
    todas as colunas para cá multiplicaria o dataset dentro da fila.
    """

    subject_type: SubjectType
    provider_id: ProviderId
    source_value: SourceValue
    #: Onde no dataset este registro está — `dataset:arquivo:linha`.
    record_ref: str
    #: O contexto que ajuda um humano a decidir sem abrir o arquivo:
    #: `competição=PREMIER_LEAGUE`, `temporada=2019-2020`. Curto e tipado
    #: como texto porque é para leitura, não para consulta.
    context: dict[str, str]

    def __post_init__(self) -> None:
        if len(self.context) > 12:
            raise ValidationError(
                f"contexto com {len(self.context)} chaves: a fila mostra contexto "
                "para decidir, não o registro inteiro"
            )

    def __str__(self) -> str:
        extra = " · ".join(f"{k}={v}" for k, v in sorted(self.context.items()))
        return f"{self.subject_type} {self.source_value.raw!r} ({extra})"


@final
@dataclass(frozen=True, slots=True)
class ResolutionReviewItem:
    """Um registro que o motor não resolveu sozinho."""

    id: str
    run_id: str
    subject: ReviewSubject
    #: Por que caiu na fila: `AMBIGUOUS` ou `REVIEW_REQUIRED`. Os dois pedem
    #: leituras diferentes de quem revisa — o primeiro é «escolha entre
    #: estes», o segundo é «confirme se é este».
    reason_status: ResolutionStatus
    candidates: tuple[ResolutionAlternative, ...]
    status: ReviewStatus
    created_at: Instant
    assigned_to: Actor | None = None
    resolved_at: Instant | None = None
    resolved_by: Actor | None = None
    #: O id da `ResolutionDecision` que a revisão produziu.
    resolution_decision_id: str | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.reason_status.needs_human:
            raise ValidationError(
                f"item de revisão criado a partir de {self.reason_status}: só "
                "AMBIGUOUS e REVIEW_REQUIRED pedem humano"
            )
        if self.status.is_open and self.resolved_at is not None:
            raise ValidationError("item aberto com instante de conclusão")
        if not self.status.is_open:
            if self.resolved_at is None or self.resolved_by is None:
                raise ValidationError(
                    f"item em {self.status} sem quem decidiu e quando — a fila "
                    "existe para registrar exatamente isso"
                )
            if self.resolved_by.is_automated:
                raise ValidationError(
                    "item de revisão fechado por ator de serviço: a fila existe "
                    "porque o automático já falhou"
                )
            if not (self.decision_reason or "").strip():
                raise ValidationError(
                    "decisão de revisão sem motivo: sem ele o registro responde "
                    "'quando' e não responde 'por quê'"
                )
        if self.status is ReviewStatus.RESOLVED and self.resolution_decision_id is None:
            raise ValidationError(
                "item RESOLVED sem decisão associada: o mapeamento teria nascido "
                "sem nada que o explicasse"
            )

    @classmethod
    def open(
        cls,
        *,
        run_id: str,
        subject: ReviewSubject,
        reason_status: ResolutionStatus,
        candidates: tuple[ResolutionAlternative, ...],
        at: Instant,
    ) -> Self:
        return cls(
            id=str(uuid.uuid4()),
            run_id=run_id,
            subject=subject,
            reason_status=reason_status,
            candidates=candidates,
            status=ReviewStatus.OPEN,
            created_at=at,
        )

    def assign_to(self, actor: Actor, *, at: Instant) -> Self:
        """Marca que alguém está olhando. Impede decisão dupla."""
        self._assert_transition(ReviewStatus.IN_REVIEW)
        if actor.is_automated:
            raise ValidationError(
                "item de revisão atribuído a ator de serviço — a fila é humana"
            )
        _ = at
        return replace(self, status=ReviewStatus.IN_REVIEW, assigned_to=actor)

    def release(self) -> Self:
        """Devolve à fila. Quem pegou percebeu que não sabe decidir."""
        self._assert_transition(ReviewStatus.OPEN)
        return replace(self, status=ReviewStatus.OPEN, assigned_to=None)

    def resolve_with(
        self,
        *,
        chosen: EntityId,
        decision_id: str,
        actor: Actor,
        reason: str,
        at: Instant,
    ) -> Self:
        """Um humano escolheu um candidato.

        A ESCOLHA PRECISA ESTAR ENTRE OS CANDIDATOS APRESENTADOS. Aceitar uma
        entidade arbitrária transformaria a fila num atalho para criar
        mapeamento sem passar pelo resolver — e o resolver é quem sabe quais
        entidades sequer eram plausíveis.

        Vincular a outra entidade é operação legítima e tem caminho próprio
        (`link_to`), que registra que a escolha veio de fora da lista.
        """
        if not any(c.canonical_entity_id == chosen for c in self.candidates):
            raise ConflictError(
                f"{chosen} não está entre os candidatos apresentados — "
                "use a vinculação explícita se a entidade certa está fora da lista",
                context={"item_id": self.id},
            )
        return self._close(
            ReviewStatus.RESOLVED,
            decision_id=decision_id,
            actor=actor,
            reason=reason,
            at=at,
        )

    def link_to(
        self,
        *,
        entity: EntityId,
        decision_id: str,
        actor: Actor,
        reason: str,
        at: Instant,
    ) -> Self:
        """Vincula a uma entidade que NÃO estava entre os candidatos.

        Legítimo — o resolver pode não ter encontrado a entidade certa por
        falta de alias — e distinto de escolher da lista: aqui o humano está
        afirmando algo que o motor não chegou a considerar, e a decisão
        registra isso pelo motivo obrigatório.
        """
        _ = entity
        return self._close(
            ReviewStatus.RESOLVED,
            decision_id=decision_id,
            actor=actor,
            reason=reason,
            at=at,
        )

    def reject(self, *, decision_id: str, actor: Actor, reason: str, at: Instant) -> Self:
        """Nenhum dos candidatos serve.

        TAMBÉM PRODUZ DECISÃO. Sem ela, um item rejeitado seria
        indistinguível de um item que nunca foi olhado — e a próxima execução
        o colocaria na fila de novo, indefinidamente.
        """
        return self._close(
            ReviewStatus.REJECTED,
            decision_id=decision_id,
            actor=actor,
            reason=reason,
            at=at,
        )

    def _close(
        self,
        destino: ReviewStatus,
        *,
        decision_id: str,
        actor: Actor,
        reason: str,
        at: Instant,
    ) -> Self:
        self._assert_transition(destino)
        if actor.is_automated:
            raise ValidationError(
                f"item fechado como {destino} por ator de serviço: a fila existe "
                "porque o automático já falhou"
            )
        if not reason.strip():
            raise ValidationError("decisão de revisão exige motivo")
        return replace(
            self,
            status=destino,
            resolved_at=at,
            resolved_by=actor,
            resolution_decision_id=decision_id if destino is ReviewStatus.RESOLVED else None,
            decision_reason=reason[:MAX_REASON_LENGTH],
        )

    def _assert_transition(self, destino: ReviewStatus) -> None:
        if destino not in _TRANSICOES[self.status]:
            raise ConflictError(
                f"transição inválida na fila: {self.status} → {destino}",
                context={"item_id": self.id, "from": self.status.value},
            )

    @property
    def best_candidate(self) -> ResolutionAlternative | None:
        return self.candidates[0] if self.candidates else None

    def __str__(self) -> str:
        return (
            f"[{self.status}] {self.subject} · {len(self.candidates)} candidato(s) "
            f"· {self.reason_status}"
        )


@final
@dataclass(frozen=True, slots=True)
class ReviewFilter:
    """Filtros da fila. Um objeto, pela mesma razão do PR-02."""

    status: ReviewStatus | None = None
    subject_type: SubjectType | None = None
    run_id: str | None = None
    assigned_to: str | None = None
