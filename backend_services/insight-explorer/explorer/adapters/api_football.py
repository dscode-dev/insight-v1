"""API-Football adapter — fixtures, calendars and squads.

https://www.api-football.com — freemium, requires `EXPLORER_API_FOOTBALL_KEY`.

Offline without a key, for the same reason as odds_api: an unsubscribed
source must show as "registered, not collecting", not raise on every pass.

QUOTA. The free plan allows ~100 requests/day. One request returns a whole
season of fixtures for one league, so a five-year backfill across two
competitions is ten requests — comfortably inside it. That shape is why this
adapter fetches per (league, season) and never per match: the per-match
endpoints are where a free plan disappears in minutes.

The season parameter is the STARTING year: our "2023-2024" is their 2023.
"""

from __future__ import annotations

import os
import time
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_BASE = "https://v3.football.api-sports.io/fixtures"

# our competition key → API-Football league id.
_LEAGUES: dict[str, int] = {
    "premier_league": 39,
    "la_liga": 140,
    "champions_league": 2,
    "brasileirao_serie_a": 71,
    "copa_do_brasil": 73,
    "libertadores": 13,
}


def _api_key() -> str:
    return os.environ.get("EXPLORER_API_FOOTBALL_KEY", "").strip()


def _start_year(season: str) -> str | None:
    """'2023-2024' → '2023'; '2023' → '2023'."""
    head = season.split("-", 1)[0]
    return head if len(head) == 4 and head.isdigit() else None


class APIFootballAdapter(SourceAdapter):
    name = "api_football"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher(source=self.name)

    @property
    def configured(self) -> bool:
        return bool(_api_key())

    def supports(self, competition_key: str) -> bool:
        return competition_key in _LEAGUES

    def health(self) -> bool:
        if not self.configured:
            return False
        try:
            self._get(_BASE, {"league": 39, "season": 2023, "last": 1})
            return True
        except FetchError:
            return False

    def _get(self, url: str, params: dict[str, object]) -> dict:
        # The key travels in a header, never in the query string: query
        # strings are logged by proxies and land in `provenance.url`, which
        # this platform writes verbatim into the raw layer.
        session = self.fetcher._session  # noqa: SLF001 - header-auth needs the session
        if session is None:
            raise FetchError("requests is not installed")
        self.fetcher._polite_wait()  # noqa: SLF001
        response = session.get(
            url, params=params,
            timeout=self.fetcher.config.request_timeout_s,
            headers={"x-apisports-key": _api_key(), "Accept": "application/json"},
        )
        self.fetcher._last_request_ts = time.monotonic()  # noqa: SLF001
        if response.status_code >= 400:
            raise FetchError(f"api-football status {response.status_code}")
        return response.json()

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        league = _LEAGUES.get(competition_key)
        year = _start_year(season)
        if league is None or not year or not self.configured:
            return
        try:
            body = self._get(_BASE, {"league": league, "season": year})
        except FetchError:
            return

        # API-Football answers 200 with an `errors` object for quota
        # exhaustion and bad parameters alike. Treating that as success would
        # record a run that collected nothing as a healthy empty season.
        errors = body.get("errors")
        if errors:
            raise FetchError(f"api-football refused: {errors}")

        retrieved = _now()
        for item in body.get("response") or []:
            fixture = item.get("fixture") or {}
            fixture_id = fixture.get("id")
            if fixture_id is None:
                continue
            yield RawArtifact(
                source=self.name,
                provider="api-football-v3",
                entity_type="fixture",
                external_id=f"af-{fixture_id}",
                competition_key=competition_key,
                season=season,
                # The key is a header, so the recorded URL carries no secret.
                url=f"{_BASE}?league={league}&season={year}",
                method="api",
                retrieved_at=retrieved,
                raw=item,
                trust_level=self.trust_level,
                source_type="historical",
                license_note="api-football.com — per plan terms",
            )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
