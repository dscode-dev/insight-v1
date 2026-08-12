"""Sentiment reader — feature-builder input source.

Consolidation Sprint 0: the Plaza HTTP reader was retired. Narrative /
sentiment features now arrive exclusively on the canonical context
stream (Sport Hub → Atlas), where they are recorded into the watcher
series store and the feature pipeline. This null implementation keeps
the SentimentReader port satisfied so the builders fall back to their
registry defaults deterministically.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID


class NullSentimentReader:
    """Always-empty reader: builders use registry defaults."""

    async def aclose(self) -> None:
        return None

    async def latest_value(self, match_id: UUID) -> float | None:  # noqa: ARG002
        return None

    async def value_5m_ago(
        self, match_id: UUID, as_of: datetime  # noqa: ARG002
    ) -> float | None:
        return None
