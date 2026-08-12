"""Feature window origin contract.

Declares how the feature window for a snapshot was assembled. Future
debugging + explainability rely on this — an inference made over a
`live` snapshot has very different latency/freshness guarantees than
one over a `historical` back-fill, and downstream explainers can
adapt the language accordingly.

Like SourceType, this enum is additive-only and the string values are
the wire contract.
"""

from __future__ import annotations

import enum


class FeatureWindowOrigin(str, enum.Enum):
    """Provenance of the feature window in a FeatureSnapshot."""

    rolling = "rolling"          # built by the periodic worker on a fixed cadence
    historical = "historical"    # back-fill / replay over archived events
    static = "static"            # features that don't vary within match
    live = "live"                # built on demand mid-match for an inference call
    aggregated = "aggregated"    # summary stat (e.g. multi-match competition window)
    unknown = "unknown"          # ingested before this tag was applied
