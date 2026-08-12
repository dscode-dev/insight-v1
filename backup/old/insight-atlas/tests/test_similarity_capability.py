"""ATLAS-SIMILARITY-C — SimilarityService conforms to SimilarityCapability."""

from __future__ import annotations

from atlas.similarity import (
    OnlineSimilarityService,
    SimilarityCapability,
    SimilarityDomain,
    SimilarityService,
)


class _NullRepo:
    async def search_matches(self, request):  # pragma: no cover - unused here
        return []

    async def batch_search_matches(self, requests):  # pragma: no cover
        return [[] for _ in requests]


def test_online_alias_is_similarity_service() -> None:
    assert OnlineSimilarityService is SimilarityService


def test_service_conforms_to_capability_protocol() -> None:
    service = SimilarityService(_NullRepo())
    assert isinstance(service, SimilarityCapability)  # runtime_checkable Protocol


def test_health_and_capabilities_are_online_descriptors() -> None:
    service = SimilarityService(_NullRepo())
    health = service.health()
    caps = service.capabilities()
    assert health.domain is SimilarityDomain.online and health.healthy is True
    assert caps.domain is SimilarityDomain.online
    assert caps.backend == "pgvector"
    assert caps.supports_cache and caps.supports_batch and caps.supports_version_filters
    assert caps.contract == "SimilarityContext"
