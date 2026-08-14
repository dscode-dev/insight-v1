"""A trilha administrativa em PostgreSQL.

SEM FOREIGN KEY PARA `datasets`, e a ausência é a decisão. A trilha precisa
sobreviver ao que ela descreve: com `ON DELETE CASCADE`, apagar um dataset
apagaria junto o registro de quem o apagou — que é exatamente a linha que
alguém iria procurar.

`detail` VAI COMO `jsonb` E NUNCA CARREGA CONTEÚDO DE DATASET. O limite é
cobrado no domínio (`AuditEntry`), antes de chegar aqui: vinte chaves, cada
valor com no máximo 512 caracteres. Sem esse teto, alguém acrescenta "a linha
que falhou" para depurar um problema, e aquilo fica — numa tabela lida por
quem tem direito de ver decisões e não necessariamente de ver o dado.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, final

from sports_intelligence.adapters.postgres.database import Database
from sports_intelligence.domain.shared.actor import Actor, ActorKind
from sports_intelligence.domain.shared.audit import AuditAction, AuditEntry
from sports_intelligence.domain.shared.identity import DatasetId
from sports_intelligence.domain.shared.temporal import instant


@final
class PostgresAuditLog:
    def __init__(self, database: Database) -> None:
        self._db = database

    async def record(self, entry: AuditEntry) -> None:
        async with self._db.acquire() as conexao:
            await conexao.execute(
                """
                INSERT INTO dataset_audit_log (
                    id, actor_id, actor_kind, action, dataset_id, file_id,
                    correlation_id, reason, detail, at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO NOTHING
                """,
                uuid.UUID(entry.id),
                entry.actor.id,
                entry.actor.kind.value,
                entry.action.value,
                entry.dataset_id.value if entry.dataset_id else None,
                uuid.UUID(entry.file_id) if entry.file_id else None,
                entry.correlation_id,
                entry.reason,
                json.dumps(entry.detail, default=str),
                entry.at,
            )

    async def recent_for_dataset(
        self, dataset_id: DatasetId, *, limit: int = 50
    ) -> Sequence[AuditEntry]:
        async with self._db.acquire() as conexao:
            linhas = await conexao.fetch(
                "SELECT * FROM dataset_audit_log WHERE dataset_id = $1 "
                "ORDER BY at DESC, id LIMIT $2",
                dataset_id.value,
                min(limit, 200),
            )
        return [_para_entrada(linha) for linha in linhas]


def _para_entrada(linha: Any) -> AuditEntry:
    bruto = linha["detail"]
    return AuditEntry(
        id=str(linha["id"]),
        actor=Actor(id=linha["actor_id"], kind=ActorKind(linha["actor_kind"])),
        action=AuditAction(linha["action"]),
        at=instant(linha["at"]),
        dataset_id=DatasetId(linha["dataset_id"]) if linha["dataset_id"] else None,
        file_id=str(linha["file_id"]) if linha["file_id"] else None,
        correlation_id=linha["correlation_id"],
        reason=linha["reason"],
        detail=json.loads(bruto) if isinstance(bruto, str) else dict(bruto or {}),
    )
