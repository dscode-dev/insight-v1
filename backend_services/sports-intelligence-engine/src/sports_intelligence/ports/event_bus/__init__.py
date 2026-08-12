"""Publicação de eventos. O domínio não sabe que Redis Streams existe."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.events.envelope import EventEnvelope


@runtime_checkable
class EventPublisherPort(Protocol):
    async def publish(self, envelope: EventEnvelope) -> None: ...

    async def publish_batch(self, envelopes: Sequence[EventEnvelope]) -> None:
        """Um lote. Existe porque publicar 200 eventos de uma partida um a um
        é 200 idas à rede, e o custo aparece no p99 do tick."""
        ...
