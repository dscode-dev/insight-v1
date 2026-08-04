"""Registry: SignalSource.kind -> SignalKindHandler. Adding a real provider
is adding one entry here (plus its own module) — no collector/engine change.
"""

from __future__ import annotations

from explorer.realtime.kinds.base import SignalKindHandler
from explorer.realtime.kinds.noop import NoopKindHandler

REGISTRY: dict[str, SignalKindHandler] = {
    "noop": NoopKindHandler(),
}


def handler_for(kind: str) -> SignalKindHandler | None:
    return REGISTRY.get(kind)
