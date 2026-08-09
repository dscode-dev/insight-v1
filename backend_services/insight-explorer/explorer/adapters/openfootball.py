"""OpenFootball (football.json) adapter — public-domain fixtures and results.

https://github.com/openfootball/football.json publishes one JSON file per
league per season, served from GitHub's raw CDN. No API key, no scraping, no
rate limit worth speaking of — it is a static file fetch.

WHY IT EARNS A PLACE next to ESPN and Football-Data. It is the only source
here that is genuinely public domain, so it can corroborate the others
without any licence question, and it covers seasons far enough back to fill
the five-year history the platform wants. Its weakness is the mirror image:
no odds, no statistics, and team names are free text, so it is a good
cross-check on WHETHER a match happened and a poor one on its details.

Season labels: this repo uses "2023-24"; the platform uses "2023-2024".
`_season_dir` converts, and a single-year label is refused rather than
guessed — see the note there.
"""

from __future__ import annotations

import time
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

# our competition key → league key in football.json.
#
# Only the two the repo actually carries from our V1 scope. Verified against
# the 2023-24 directory listing, which holds at.1, de.1, de.2, en.1, en.2,
# es.1, fr.1, it.1, nl.1, pt.1 — domestic leagues only.
#
# Champions League, Libertadores, Copa do Brasil and Brasileirão are NOT here.
# Claiming them would make `supports()` promise coverage that resolves to a
# 404, and the scheduler would keep planning tasks that can only come back
# empty.
_LEAGUES: dict[str, str] = {
    "premier_league": "en.1",
    "la_liga": "es.1",
}

_BASE = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{league}.json"


def _season_dir(season: str) -> str | None:
    """'2023-2024' → '2023-24'.

    A single-year label like '2023' is REFUSED, not converted. European
    seasons span two calendar years and the repo names them that way; picking
    2023-24 over 2022-23 for the label '2023' would be a guess, and a wrong
    guess silently fetches a different season's fixtures under the label the
    operator asked for.
    """
    if "-" not in season:
        return None
    start, end = season.split("-", 1)
    if len(start) == 4 and len(end) == 4:
        return f"{start}-{end[2:]}"
    if len(start) == 4 and len(end) == 2:
        return season
    return None


class OpenFootballAdapter(SourceAdapter):
    name = "openfootball"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher()

    def supports(self, competition_key: str) -> bool:
        return competition_key in _LEAGUES

    def health(self) -> bool:
        try:
            self.fetcher.get_json(_BASE.format(season="2023-24", league="en.1"))
            return True
        except FetchError:
            return False

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        league = _LEAGUES.get(competition_key)
        season_dir = _season_dir(season)
        if not league or not season_dir:
            return
        url = _BASE.format(season=season_dir, league=league)
        try:
            body = self.fetcher.get_json(url)
        except FetchError:
            # A season this repo does not carry is a 404, which is normal
            # coverage — not a source outage. Raising would open a
            # source_offline ticket for every season before the repo starts.
            return

        matches = body.get("matches") or []
        retrieved = _now()
        for index, match in enumerate(matches):
            home, away = match.get("team1"), match.get("team2")
            if not home or not away:
                continue
            yield RawArtifact(
                source=self.name,
                provider="openfootball-json-v1",
                entity_type="fixture",
                external_id=f"of-{league}-{season_dir}-{index:04d}",
                competition_key=competition_key,
                season=season,
                url=url,
                method="file",
                retrieved_at=retrieved,
                raw=match,
                trust_level=self.trust_level,
                source_type="historical",
                license_note="openfootball/football.json — public domain",
            )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
