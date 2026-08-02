"""Wikipedia adapter (secondary, enrichment tier).

Wikipedia is a **low-trust corroboration / enrichment** source, not a
match-results feed: per-match score tables vary wildly by article and are not
reliably machine-parseable. This adapter therefore confirms the season article
exists (via the MediaWiki API) and is registered as a source so the
multi-source framework records its participation; it does not fabricate
fixtures. Promoting it to structured per-match extraction is future work.
"""

from __future__ import annotations

from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_API = "https://en.wikipedia.org/w/api.php"

_SEASON_ARTICLE = {
    "brasileirao_serie_a": "{season} Campeonato Brasileiro Série A",
    "libertadores": "{season} Copa Libertadores",
    "world_cup": "{season} FIFA World Cup",
    "premier_league": "{season} Premier League",
    "la_liga": "{season} La Liga",
}


class WikipediaAdapter(SourceAdapter):
    name = "wikipedia"
    trust_level = "low"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher()

    def supports(self, competition_key: str) -> bool:
        return competition_key in _SEASON_ARTICLE

    def health(self) -> bool:
        try:
            self.fetcher.get_json(_API, params={"action": "query", "meta": "siteinfo",
                                                 "format": "json"})
            return True
        except FetchError:
            return False

    def article_exists(self, competition_key: str, season: str) -> bool:
        title = _SEASON_ARTICLE[competition_key].format(season=season)
        data = self.fetcher.get_json(_API, params={
            "action": "query", "titles": title, "format": "json"})
        pages = (data.get("query") or {}).get("pages") or {}
        return all(int(pid) > 0 for pid in pages)

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        # Enrichment-tier: confirm coverage exists; yield no fixtures (honest).
        # The framework records that Wikipedia was consulted via health/coverage.
        return iter(())
