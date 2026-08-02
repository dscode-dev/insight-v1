"""Production vector similarity: contracts, storage, and the shared service."""

from atlas.similarity.cache import SimilarityCache
from atlas.similarity.capability import (
    SimilarityCapabilities,
    SimilarityCapability,
    SimilarityDomain,
    SimilarityHealth,
)
from atlas.similarity.contracts import (
    SimilarityConfidence,
    SimilarityContext,
    SimilarityDistribution,
    SimilarityFilters,
    SimilarityMatch,
    SimilaritySearchRequest,
    SimilaritySearchResult,
    TimeWindow,
)
from atlas.similarity.repository import SimilarityRepository
from atlas.similarity.service import OnlineSimilarityService, SimilarityService

__all__ = [
    "OnlineSimilarityService",
    "SimilarityCache",
    "SimilarityCapabilities",
    "SimilarityCapability",
    "SimilarityConfidence",
    "SimilarityContext",
    "SimilarityDistribution",
    "SimilarityDomain",
    "SimilarityFilters",
    "SimilarityHealth",
    "SimilarityMatch",
    "SimilarityRepository",
    "SimilaritySearchRequest",
    "SimilaritySearchResult",
    "SimilarityService",
    "TimeWindow",
]
