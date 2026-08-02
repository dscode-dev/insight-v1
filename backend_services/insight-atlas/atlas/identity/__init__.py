"""Cross-provider match identity — Sprint 6.2 Part 1 (Atlas side).

Resolves provider-specific match observations into a single
canonical_match_id so every downstream context, feature, odds view and
inference unifies across API-Football, Football-Data and The Odds API.
"""

from atlas.identity.models import (
    CANONICAL_NAMESPACE,
    CanonicalMatch,
    ProviderMatchIdentity,
    mint,
    normalize,
)
from atlas.identity.registry import IdentityRegistry
from atlas.identity.resolver import IdentityResolver

__all__ = [
    "CANONICAL_NAMESPACE",
    "CanonicalMatch",
    "IdentityRegistry",
    "IdentityResolver",
    "ProviderMatchIdentity",
    "mint",
    "normalize",
]
