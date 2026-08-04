"""Reference `SignalKindHandler` — captures nothing, never fails. Lets the
realtime framework (collector, publisher, lake layer, Console management) be
exercised end-to-end before a real news/signal provider is wired in.
"""

from __future__ import annotations

from explorer.collectors.http import PoliteFetcher
from explorer.realtime.models import CapturedSignal, SignalSource


class NoopKindHandler:
    def poll(self, source: SignalSource, fetcher: PoliteFetcher) -> list[CapturedSignal]:
        return []
