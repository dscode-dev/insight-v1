"""Canonical compatibility metadata for persisted embeddings (ATLAS-VECTOR-B).

Every value here originates from an Atlas runtime CONSTANT — never fabricated.
These stamp the version-aware filter columns added by migration 0016
(feature_schema_version / signal_catalog_version / behavior_catalog_version /
similarity_metadata) so the online SimilarityRepository can compare only
compatible vectors. Domain facets the source object does not carry
(season / market_type / match_phase) stay ``None`` — never invented.
"""

from __future__ import annotations

import json
import os

from atlas.intelligence.kernel import INTELLIGENCE_SCHEMA_VERSION
from atlas.vector_memory.contracts import EMBEDDING_VERSION

# The signal + behavior taxonomies the embedding's names come from are versioned
# by the intelligence schema — that IS their catalog version.
SIGNAL_CATALOG_VERSION = INTELLIGENCE_SCHEMA_VERSION
BEHAVIOR_CATALOG_VERSION = INTELLIGENCE_SCHEMA_VERSION

# Mirrors Settings.feature_schema_version (alias FEATURE_SCHEMA_VERSION, default
# 2). Read from the env directly so stamping a version never drags in unrelated
# runtime settings (Redis/Anvil) — same canonical source of truth as Settings.
_DEFAULT_FEATURE_SCHEMA_VERSION = "2"


def feature_schema_version() -> str:
    """The canonical Atlas feature schema version, e.g. ``feature_schema_v2``."""
    raw = os.environ.get("FEATURE_SCHEMA_VERSION", _DEFAULT_FEATURE_SCHEMA_VERSION)
    return f"feature_schema_v{raw}"


def compatibility_params(
    *,
    source: str,
    season: str | None = None,
    market_type: str | None = None,
    match_phase: str | None = None,
    embedding_version: str = EMBEDDING_VERSION,
) -> dict[str, object]:
    """Bind params for the migration-0016 compat columns, all canonical.

    `embedding_version` defaults to the frozen v1 constant (unchanged
    behavior for every existing caller); v2 upserts pass
    `EMBEDDING_VERSION_V2` explicitly. `feature_schema_version()`/
    `SIGNAL_CATALOG_VERSION`/`BEHAVIOR_CATALOG_VERSION` intentionally do
    NOT vary with it — those describe System A's ML feature schema and
    the general Intelligence Report contract respectively, both frozen
    for V1 and shared by subsystems this work doesn't touch.
    """
    fsv = feature_schema_version()
    return {
        "feature_schema_version": fsv,
        "signal_catalog_version": SIGNAL_CATALOG_VERSION,
        "behavior_catalog_version": BEHAVIOR_CATALOG_VERSION,
        "season": season,
        "market_type": market_type,
        "match_phase": match_phase,
        "similarity_metadata": json.dumps(
            {
                "source": source,
                "embedding_version": embedding_version,
                "feature_schema_version": fsv,
                "signal_catalog_version": SIGNAL_CATALOG_VERSION,
                "behavior_catalog_version": BEHAVIOR_CATALOG_VERSION,
            }
        ),
    }
