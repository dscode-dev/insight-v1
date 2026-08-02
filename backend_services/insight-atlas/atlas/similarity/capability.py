"""SimilarityCapability — the Atlas Similarity domain contract (ATLAS-SIMILARITY-C).

A lightweight, behaviour-free abstraction that BOTH similarity domains implement:

  * OnlineSimilarityService  — realtime pgvector (this package's SimilarityService)
  * OfflineSimilarityService — dataset/report similarity (future; wraps
    DeterministicVectorIndex / SimilarityEngine)

This is architectural formalization only — it introduces no algorithm, no runtime
behaviour, and does not redesign any existing service. Existing services simply
conform to the protocol (SimilarityService already provides `context` + `batch`;
`health` + `capabilities` are additive, side-effect-free descriptors).
"""

from __future__ import annotations

import enum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from atlas.similarity.contracts import SimilarityContext, SimilaritySearchRequest


class SimilarityDomain(str, enum.Enum):
    online = "online"  # realtime pgvector
    offline = "offline"  # dataset / report, deterministic batch


class SimilarityHealth(BaseModel):
    """Side-effect-free readiness snapshot of a similarity provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: SimilarityDomain
    healthy: bool
    detail: str = ""


class SimilarityCapabilities(BaseModel):
    """Declarative description of what a similarity provider supports."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: SimilarityDomain
    backend: str  # e.g. "pgvector" | "in_memory_dataset"
    supports_cache: bool
    supports_batch: bool
    supports_version_filters: bool
    contract: str = "SimilarityContext"


@runtime_checkable
class SimilarityCapability(Protocol):
    """The single similarity domain contract. Responsibilities only."""

    async def context(
        self,
        request: SimilaritySearchRequest,
        *,
        canonical_match_id: str | None = None,
        consumer: str = "unknown",
    ) -> SimilarityContext: ...

    async def batch(
        self,
        requests: list[SimilaritySearchRequest],
        *,
        canonical_match_ids: list[str | None] | None = None,
        consumer: str = "unknown",
    ) -> list[SimilarityContext]: ...

    def health(self) -> SimilarityHealth: ...

    def capabilities(self) -> SimilarityCapabilities: ...
