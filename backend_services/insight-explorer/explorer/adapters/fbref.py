"""FBRef adapter (multi-source, high trust) — ML-B.6 Part 8.

FBRef (StatsBomb data) is the richest historical source and covers Copa
Libertadores, but it serves HTML (no JSON API) and is aggressively
anti-scraping (Cloudflare 429/403). This adapter makes a real, polite attempt
to fetch a competition season's "Scores & Fixtures" table and parse finished
matches with stdlib `html.parser`. When FBRef blocks the request it raises
FetchError → the JobRunner isolates the source, opens a ticket, and the
Console source panel shows FBRef as failing — honest, visible behaviour rather
than silent emptiness.

Comp ids: Copa Libertadores = 14.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_COMP = {
    "libertadores": ("14", "Copa-Libertadores"),
    "premier_league": ("9", "Premier-League"),
    "la_liga": ("12", "La-Liga"),
}
_BASE = "https://fbref.com/en/comps/{cid}/{season}/schedule/{season}-{slug}-Scores-and-Fixtures"


class _FixtureTableParser(HTMLParser):
    """Extracts rows from FBRef's schedule table: date, home, score, away."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []
        self._row: dict[str, str] = {}
        self._stat: str | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = dict(attrs)
        if tag == "tr":
            self._row = {}
        if tag in ("td", "th"):
            self._stat = d.get("data-stat")
            self._depth = 1

    def handle_data(self, data: str) -> None:
        if self._stat and self._depth:
            self._row[self._stat] = (self._row.get(self._stat, "") + data).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self._stat = None
            self._depth = 0
        if tag == "tr" and self._row.get("home_team") and self._row.get("away_team"):
            self.rows.append(self._row)


class FBRefAdapter(SourceAdapter):
    name = "fbref"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher()

    def supports(self, competition_key: str) -> bool:
        return competition_key in _COMP

    def health(self) -> bool:
        try:
            self.fetcher.get_text("https://fbref.com/en/")
            return True
        except FetchError:
            return False

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        cid, slug = _COMP[competition_key]
        url = _BASE.format(cid=cid, season=season, slug=slug)
        html = self.fetcher.get_text(url)  # raises FetchError if blocked → isolated
        parser = _FixtureTableParser()
        parser.feed(html)
        for i, row in enumerate(parser.rows):
            score = row.get("score", "")
            if not score or "–" not in score and "-" not in score:
                continue  # not played yet
            ext = f"fbref-{cid}-{season}-{i:04d}"
            yield RawArtifact(
                source=self.name, provider="fbref-schedule-v1", entity_type="fixture",
                external_id=ext, competition_key=competition_key, season=season,
                url=url, method="scrape", retrieved_at=_now(), raw=row,
                trust_level=self.trust_level, source_type="historical",
                license_note="FBRef/StatsBomb; research use",
            )


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
