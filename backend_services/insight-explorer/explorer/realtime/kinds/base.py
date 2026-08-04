"""Signal-source kind contract (ML-D Phase B).

A kind handler knows only how to poll ONE `SignalSource` and yield
`CapturedSignal`s from it — no persistence, no publishing, no retry policy
(the collector owns those, same separation as `SourceAdapter` for historical
fixture collection in explorer/adapters/base.py). Adding a real provider
(a news API, an RSS feed, a crawler) means implementing this protocol and
registering it in `explorer/realtime/kinds/__init__.py::REGISTRY` — no
collector/engine change.
"""

from __future__ import annotations

from typing import Protocol

from explorer.collectors.http import PoliteFetcher
from explorer.realtime.models import CapturedSignal, SignalSource


class SignalKindHandler(Protocol):
    def poll(self, source: SignalSource, fetcher: PoliteFetcher) -> list[CapturedSignal]:
        """Return newly-captured signals for this source. Raise on failure
        (network errors etc.) — the collector isolates and tickets it; never
        swallow errors here and return an empty list to mean 'failed'."""
        ...
