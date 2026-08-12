"""Shared contract vocabulary for Atlas + the upcoming Sports Data Hub.

Anything in this package is intentionally framed as a CONTRACT — the
Go-side Sports Data Hub will mirror these enums byte-for-byte (string
values are stable, additive-only, never reordered) so messages crossing
the Python/Go boundary deserialise without translation.
"""

from atlas.contracts.no_prediction import (
    assert_no_prediction_keys,
    assert_no_prediction_phrases,
    scan_payload,
)
from atlas.contracts.source import SourceRef, SourceType
from atlas.contracts.window import FeatureWindowOrigin

__all__ = [
    "FeatureWindowOrigin",
    "SourceRef",
    "SourceType",
    "assert_no_prediction_keys",
    "assert_no_prediction_phrases",
    "scan_payload",
]
