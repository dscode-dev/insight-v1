"""Armazenamento de objetos: o bruto imutável e os arquivos reconstruíveis."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStorePort(Protocol):
    """S3/MinIO, visto pelo domínio como quatro operações.

    SEM `delete`, E A AUSÊNCIA É A DECISÃO. A camada bruta é imutável por
    contrato (ADR-0004): ela é a única cópia do que o provedor de fato mandou,
    e é dela que toda reconstrução parte. Apagar é operação administrativa
    deliberada, não algo que um caminho de código alcança por engano.
    """

    async def put(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...

    def list_prefix(self, prefix: str) -> AsyncIterator[str]: ...
