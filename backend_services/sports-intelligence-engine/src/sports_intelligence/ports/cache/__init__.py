"""Cache: o estado quente e a inteligência materializada.

É O PORT QUE SUSTENTA O CAMINHO DE LEITURA (ADR-0010). O cálculo pesado roda
uma vez por estado e o resultado é materializado aqui; N usuários lendo a mesma
partida leem daqui, e não disparam cálculo.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CachePort(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, *, ttl_seconds: int | None = None) -> None:
        """TTL explícito, e `None` quer dizer "sem expiração".

        Sem TTL default: um default esconde a decisão de por quanto tempo um
        dado continua verdadeiro, e essa decisão é diferente para estado ao
        vivo e para inteligência materializada.
        """
        ...

    async def delete(self, key: str) -> None: ...
