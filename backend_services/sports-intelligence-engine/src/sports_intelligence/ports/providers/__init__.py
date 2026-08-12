"""Provedores externos. Nada do formato deles atravessa esta fronteira."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol, runtime_checkable

from sports_intelligence.domain.shared.identity import ProviderId
from sports_intelligence.domain.shared.provenance import DataProvenance


@runtime_checkable
class LiveProviderPort(Protocol):
    """Um provedor de dados ao vivo.

    O PAYLOAD SAI COMO `Mapping[str, Any]` CRU, E É DELIBERADO. Tipar aqui o
    formato de um provedor faria o tipo dele atravessar a fronteira e chegar
    ao domínio — que é exatamente o que os testes de arquitetura proíbem. A
    tradução para o canônico é da camada de normalização, que conhece os dois
    lados e é o único lugar onde o formato do provedor pode aparecer.
    """

    @property
    def provider_id(self) -> ProviderId: ...

    def stream(
        self, *, since_token: str | None
    ) -> AsyncIterator[tuple[Mapping[str, Any], DataProvenance]]:
        """Eventos crus, cada um com sua procedência.

        A procedência sai JUNTO e não depois: montá-la mais adiante exigiria
        que a camada seguinte soubesse quando o provedor observou, o que só
        este adapter sabe.
        """
        ...
