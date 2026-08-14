"""Publicação de eventos — em log estruturado, por enquanto.

POR QUE NÃO REDIS STREAMS AGORA. O ADR-0004 reserva Streams para o barramento,
e ele continua sendo o destino. Mas os quatro eventos deste PR não têm, hoje,
nenhum consumidor: o PR-03 vai consumir `dataset.staged`, e ele não existe.
Instalar Redis, subir um contêiner e manter um grupo de consumo para uma fila
que ninguém lê é infraestrutura que só produz operação.

O QUE O LOG ENTREGA ENQUANTO ISSO. Os eventos ficam observáveis e
correlacionáveis — que é a metade do valor deles agora — e a troca por Streams
é a substituição de uma classe atrás do mesmo `EventPublisherPort`, sem tocar
em nenhum caso de uso.

O PAYLOAD VAI INTEIRO PARA O LOG, e isso é seguro por construção: nenhum dos
quatro eventos carrega conteúdo de dataset. Eles carregam identificadores,
hashes e contagens. Se algum evento futuro precisar carregar dado, este
publisher deixa de servir — e a linha acima é o lembrete de por quê.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import final

from sports_intelligence.domain.events.envelope import EventEnvelope

_log = logging.getLogger("sports_intelligence.events")


@final
class LoggingEventPublisher:
    """Registra o envelope no log estruturado."""

    async def publish(self, envelope: EventEnvelope) -> None:
        _log.info(
            "evento publicado",
            extra={
                "event_id": str(envelope.event_id),
                "event_type": envelope.event_type,
                "schema_version": str(envelope.schema_version),
                "correlation_id": str(envelope.correlation_id),
                "occurred_at": envelope.occurred_at.isoformat(),
                "payload": envelope.payload,
            },
        )

    async def publish_batch(self, envelopes: Sequence[EventEnvelope]) -> None:
        for envelope in envelopes:
            await self.publish(envelope)


@final
class CollectingEventPublisher:
    """Guarda os envelopes em memória. Duplo de teste, no código de produção.

    AQUI E NÃO EM `tests/`, pela mesma razão do `FrozenClock` (PR-00): um port
    cujo único duplo é reinventado por cada teste é um port com duplos que
    divergem. Um deles esquece de acumular, outro acumula só o último, e os
    testes passam a verificar coisas diferentes achando que verificam a mesma.
    """

    def __init__(self) -> None:
        self.published: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.published.append(envelope)

    async def publish_batch(self, envelopes: Sequence[EventEnvelope]) -> None:
        self.published.extend(envelopes)

    def of_type(self, event_type: str) -> list[EventEnvelope]:
        return [e for e in self.published if e.event_type == event_type]
