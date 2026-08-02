"""Source-agnostic adapter contract (Step 2).

A source adapter knows *only* how to fetch raw artifacts from one source and
yield them with provenance. It performs NO normalization, NO validation, NO
business logic — that lives downstream (normalizers/validators/pipeline).
Swapping ESPN for FBRef/Football-Data is implementing this interface; the
collector and the rest of the pipeline never change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol


@dataclass
class RawArtifact:
    """One raw source response, preserved verbatim in the raw/ layer."""

    source: str
    provider: str
    entity_type: str
    external_id: str
    competition_key: str
    season: str
    url: str
    method: str  # api | scrape | file | manual
    retrieved_at: str
    raw: dict[str, Any]
    trust_level: str = "medium"
    source_type: str = "historical"
    license_note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(Protocol):
    """Every source implements this. `name` is the logical source family."""

    name: str
    trust_level: str

    def supports(self, competition_key: str) -> bool: ...

    def health(self) -> bool:
        """Cheap reachability probe (drives explorer_sources_online)."""
        ...

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        """Yield raw artifacts for a whole season. Network errors must be
        raised (the collector owns retry/backoff/ticketing), not swallowed."""
        ...
