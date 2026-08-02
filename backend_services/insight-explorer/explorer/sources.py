"""Source registry — the single place sources are wired in.

Adding a source is appending one adapter here; the multi-source runner,
scheduler and reconciler need no change (Step 2 source-agnosticism extended
to ML-B.5 multi-source).
"""

from __future__ import annotations

from explorer.adapters.base import SourceAdapter
from explorer.adapters.espn import ESPNAdapter
from explorer.adapters.fbref import FBRefAdapter
from explorer.adapters.football_data import FootballDataAdapter
from explorer.adapters.wikipedia import WikipediaAdapter


def build_default_registry() -> list[SourceAdapter]:
    """Ordered by precedence; the reconciler treats higher-trust sources as
    the tie-breaker. ESPN (covers Brazil/SA/WC), FBRef (rich, covers
    Libertadores), Football-Data (Europe), Wikipedia (enrichment)."""
    return [ESPNAdapter(), FBRefAdapter(), FootballDataAdapter(), WikipediaAdapter()]


def adapters_for(competition_key: str, registry: list[SourceAdapter] | None = None) -> list[SourceAdapter]:
    reg = registry if registry is not None else build_default_registry()
    return [a for a in reg if a.supports(competition_key)]
