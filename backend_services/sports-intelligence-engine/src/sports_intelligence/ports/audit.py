"""Onde a trilha administrativa é gravada.

UM MÉTODO E MEIO. `record` grava, `recent` lê. Não há busca por texto, não há
agregação, não há retenção configurável — nada disso é necessário para
responder "quem promoveu este dataset e por quê", e cada um deles seria uma
peça a manter antes de existir quem a use.

GRAVAR AUDITORIA NÃO PODE DERRUBAR A OPERAÇÃO, e a decisão é do chamador, não
deste port. O contrato é: `record` levanta se falhar. Quem chama decide se
aquilo é fatal — e para as decisões humanas (promover, rejeitar) é: uma
promoção que aconteceu e não foi registrada é pior do que uma promoção que
falhou, porque a primeira é invisível.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sports_intelligence.domain.shared.audit import AuditEntry
from sports_intelligence.domain.shared.identity import DatasetId


@runtime_checkable
class AuditPort(Protocol):
    async def record(self, entry: AuditEntry) -> None:
        """Grava uma entrada. Levanta se não conseguir."""
        ...

    async def recent_for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 50
    ) -> Sequence[AuditEntry]:
        """As últimas entradas de um dataset, da mais nova para a mais velha."""
        ...
