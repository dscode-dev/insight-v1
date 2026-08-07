"""The Odds API adapter — live and recent bookmaker odds.

https://the-odds-api.com — freemium, requires `EXPLORER_ODDS_API_KEY`.

WITHOUT A KEY IT IS OFFLINE, NOT BROKEN. `health()` returns False and
`fetch_season` yields nothing, so the source appears in the console as a
registered source that is not collecting, with a reason. The alternative —
raising — would open a `source_offline` ticket on every planning pass for a
source nobody has subscribed to yet. Same shape as Nexus's LLM providers:
registering an adapter, holding a credential and being switched on are three
separate things.

QUOTA IS THE REAL CONSTRAINT, not rate. The free plan meters *requests per
month*, and each request returns every upcoming match for a sport at once.
So this adapter fetches one snapshot per call and never walks a date range —
a per-day loop like ESPN's would exhaust a month's quota in an afternoon.

HISTORICAL ODDS ARE A PAID FEATURE. The free plan serves UPCOMING fixtures
only, which means this source cannot fill the five-year history; it can only
start accumulating from the day it is switched on. Football-Data.co.uk is
where the historical odds come from.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds"

# our competition key → the API's sport key.
_SPORTS: dict[str, str] = {
    "premier_league": "soccer_epl",
    "la_liga": "soccer_spain_la_liga",
    "champions_league": "soccer_uefa_champs_league",
    "brasileirao_serie_a": "soccer_brazil_campeonato",
}


def _api_key() -> str:
    return os.environ.get("EXPLORER_ODDS_API_KEY", "").strip()


class OddsAPIAdapter(SourceAdapter):
    name = "odds_api"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher(source=self.name)

    @property
    def configured(self) -> bool:
        """Read at CALL time, not at construction.

        A key added to the environment takes effect on the next run instead
        of on the next rebuild, and a test can set it without reconstructing
        the adapter.
        """
        return bool(_api_key())

    def supports(self, competition_key: str) -> bool:
        # Coverage is independent of configuration: this source covers the
        # competition whether or not we currently hold a key. Conflating the
        # two would make the console report "not covered" for what is really
        # "not subscribed".
        return competition_key in _SPORTS

    def health(self) -> bool:
        if not self.configured:
            return False
        try:
            self.fetcher.get_json(
                "https://api.the-odds-api.com/v4/sports",
                params={"apiKey": _api_key()},
            )
            return True
        except FetchError:
            return False

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        sport = _SPORTS.get(competition_key)
        if not sport or not self.configured:
            return
        url = _BASE.format(sport=sport)
        try:
            events = self.fetcher.get_json(
                url,
                params={
                    "apiKey": _api_key(),
                    "regions": "eu,uk",
                    "markets": "h2h",
                    "oddsFormat": "decimal",
                },
            )
        except FetchError:
            return
        if not isinstance(events, list):
            return

        retrieved = _now()
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            for book in event.get("bookmakers") or []:
                for market in book.get("markets") or []:
                    yield RawArtifact(
                        source=self.name,
                        provider="the-odds-api-v4",
                        entity_type="odds_snapshot",
                        external_id=f"oa-{event_id}-{book.get('key')}-{market.get('key')}",
                        competition_key=competition_key,
                        season=season,
                        url=url,
                        method="api",
                        retrieved_at=retrieved,
                        raw={
                            "_event": {k: event.get(k) for k in
                                       ("id", "commence_time", "home_team", "away_team")},
                            "bookmaker": book.get("key"),
                            "bookmaker_title": book.get("title"),
                            "last_update": market.get("last_update") or book.get("last_update"),
                            "market": market.get("key"),
                            "outcomes": market.get("outcomes") or [],
                        },
                        trust_level=self.trust_level,
                        source_type="live",
                        license_note="the-odds-api.com — per plan terms",
                    )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
