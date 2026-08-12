"""O envelope interno de eventos — e por que ele não conhece broker nenhum.

O QUE ELE CARREGA ALÉM DO PAYLOAD. Um evento sem causa e sem correlação é
impossível de investigar: quando algo dá errado três saltos adiante, a única
pergunta que importa é "o que originou isto", e sem `causation_id` a resposta
exige reconstruir a sequência a partir de timestamps — que empatam.

    correlation_id   amarra tudo que veio de UM gatilho (um tick, um import)
    causation_id     aponta para O evento imediatamente anterior

Correlação responde "o que mais aconteceu por causa disso"; causação responde
"o que exatamente causou isto". Uma não substitui a outra.

DOIS INSTANTES, NÃO UM. `occurred_at` é quando o fato aconteceu no mundo;
`produced_at` é quando este envelope foi criado. Reprocessar um evento antigo
gera um envelope novo com `produced_at` de agora e `occurred_at` do passado —
e é essa diferença que distingue replay de tempo real.

SEM BROKER AQUI. Nada neste módulo sabe que Redis Streams existe. A publicação
é `EventPublisherPort`, e o adapter que a implementa é quem conhece
`XADD`. Trocar de transporte não deve tocar um evento sequer.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Self, final

from sports_intelligence.domain.shared.identity import MatchId
from sports_intelligence.domain.shared.temporal import Instant
from sports_intelligence.domain.shared.versioning import Version


@final
@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion(Version):
    """A versão do formato do payload. Um consumidor que não a conhece deve
    recusar o evento, não adivinhar os campos."""

    KIND = "versão de schema de evento"


@final
@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """Um fato interno, com o que ele é e de onde veio.

    IMUTÁVEL. Um evento é um registro do que aconteceu; alterá-lo é reescrever
    o passado. Encadeamento se faz com `caused_by`, que produz um envelope
    NOVO apontando para este.
    """

    event_id: uuid.UUID
    event_type: str
    schema_version: SchemaVersion
    occurred_at: Instant
    produced_at: Instant
    correlation_id: uuid.UUID
    causation_id: uuid.UUID | None
    payload: Mapping[str, Any]
    match_id: MatchId | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        tipo = self.event_type.strip()
        if not tipo:
            raise ValueError("event_type vazio: um evento sem tipo não tem consumidor")
        # Ponto separando domínio e fato — `match.goal.scored`. A convenção
        # existe para que o roteamento por prefixo seja possível sem que cada
        # consumidor invente o próprio parser.
        if tipo != tipo.lower() or " " in tipo:
            raise ValueError(
                f"event_type {self.event_type!r} inválido: minúsculas e pontos, "
                "por exemplo 'match.goal.scored'"
            )
        if self.produced_at < self.occurred_at:
            raise ValueError(
                "produced_at é anterior a occurred_at: o envelope não pode ser criado "
                "antes de o fato acontecer"
            )
        if self.causation_id == self.event_id:
            raise ValueError("um evento não pode ser a própria causa")

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        schema_version: SchemaVersion,
        occurred_at: Instant,
        produced_at: Instant,
        payload: Mapping[str, Any],
        correlation_id: uuid.UUID | None = None,
        match_id: MatchId | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> Self:
        """Um evento novo, raiz de uma cadeia.

        Sem `correlation_id`, ele nasce sendo a própria correlação — é o
        gatilho. Eventos derivados usam `caused_by` e herdam a dela.
        """
        return cls(
            event_id=uuid.uuid4(),
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at,
            produced_at=produced_at,
            correlation_id=correlation_id or uuid.uuid4(),
            causation_id=None,
            payload=dict(payload),
            match_id=match_id,
            metadata=dict(metadata or {}),
        )

    def caused_by(
        self,
        *,
        event_type: str,
        schema_version: SchemaVersion,
        occurred_at: Instant,
        produced_at: Instant,
        payload: Mapping[str, Any],
        metadata: Mapping[str, str] | None = None,
    ) -> EventEnvelope:
        """Um evento derivado deste. Herda a correlação, aponta a causa.

        É o que torna a cadeia inteira reconstruível a partir de qualquer elo.
        """
        return EventEnvelope(
            event_id=uuid.uuid4(),
            event_type=event_type,
            schema_version=schema_version,
            occurred_at=occurred_at,
            produced_at=produced_at,
            correlation_id=self.correlation_id,
            causation_id=self.event_id,
            payload=dict(payload),
            match_id=self.match_id,
            metadata=dict(metadata or {}),
        )

    @property
    def is_root(self) -> bool:
        return self.causation_id is None
