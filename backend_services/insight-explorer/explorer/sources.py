"""Source registry — the single place sources are wired in.

Adding a source is appending one adapter here; the multi-source runner,
scheduler and reconciler need no change (Step 2 source-agnosticism extended
to ML-B.5 multi-source), and the Console's Sources screen picks it up because
`pipelines.catalog` builds itself from this list.

REACHABILITY, VERIFIED FROM THE COLLECTING HOST (2026-08-07). Whether a
source works is a property of the network the collector sits on, not of the
code, so it was measured from the Robozão rather than from a workstation:

    football_data  200   fixtures + stats + odds, five seasons
    openfootball   200   fixtures, public domain
    statsbomb      200   fixtures, curated archive
    wikipedia      200   enrichment
    espn           403   blocked at this IP
    fbref          403   Cloudflare interstitial

ESPN and FBRef are kept registered. They are correct code against sources
that currently refuse this host, and their adapters report `health() = False`,
which surfaces in the console as a source that is registered and offline —
the honest state. Deleting them would erase the coverage they provide from
anywhere else and hide the fact that the platform is blocked.

UNDERSTAT IS DELIBERATELY ABSENT. Its robots.txt is `Disallow: /` for every
user agent. The site is reachable and the data is good; collecting it anyway
would be ignoring an explicit instruction from the operator of a small site,
which is not a thing to do quietly inside a registry.
"""

from __future__ import annotations

from explorer.adapters.api_football import APIFootballAdapter
from explorer.adapters.base import SourceAdapter
from explorer.adapters.espn import ESPNAdapter
from explorer.adapters.fbref import FBRefAdapter
from explorer.adapters.football_data import FootballDataAdapter
from explorer.adapters.odds_api import OddsAPIAdapter
from explorer.adapters.openfootball import OpenFootballAdapter
from explorer.adapters.statsbomb import StatsBombAdapter
from explorer.adapters.wikipedia import WikipediaAdapter


def build_default_registry() -> list[SourceAdapter]:
    """Ordered by precedence; the reconciler treats higher-trust sources as
    the tie-breaker.

    The order leads with what actually collects today, so a run that stops
    early has still gathered the most from the fewest sources.
    """
    return [
        # Verified collecting.
        FootballDataAdapter(),   # fixtures + stats + odds, Europe
        OpenFootballAdapter(),   # fixtures, public domain, Europe
        StatsBombAdapter(),      # fixtures, curated archive
        # Metered APIs — offline until a key is configured.
        APIFootballAdapter(),    # fixtures, broad coverage incl. South America
        OddsAPIAdapter(),        # odds, upcoming only on the free plan
        # Registered but currently refused by the source.
        ESPNAdapter(),
        FBRefAdapter(),
        WikipediaAdapter(),      # enrichment
    ]


def adapters_for(competition_key: str, registry: list[SourceAdapter] | None = None) -> list[SourceAdapter]:
    reg = registry if registry is not None else build_default_registry()
    return [a for a in reg if a.supports(competition_key)]
