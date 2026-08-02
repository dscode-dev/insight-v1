"""ESPN hidden-JSON-API adapter (Step 2/5).

ESPN exposes an undocumented but stable public JSON scoreboard:
    site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates=YYYYMMDD

It is the approved source that actually *covers Brazil* (Football-Data.co.uk
has no Brazilian leagues; FBRef is scraper-hostile) — see ML_B_SOURCE_DECISION.
This adapter only fetches + preserves raw events; normalization is downstream.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher
from explorer.config import COMPETITIONS

_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"

# Realistic collection windows (month/day) per competition. Keeps the crawl
# polite without missing matches; unknown competitions fall back to full year.
_SEASON_WINDOWS = {
    # Brasileirão is a calendar-year league. 2020 ran Aug 2020 → Feb 2021
    # (COVID), so its window spills into the next year.
    "brasileirao_serie_a": {
        "default": ((4, 1), (12, 20)),
        2020: ((8, 1), (12, 31), 2021, (1, 1), (2, 28)),
    },
    # Copa Libertadores: calendar-year, ~Feb (qualifiers) → Nov (final).
    "libertadores": {
        "default": ((2, 1), (11, 30)),
    },
    # World Cup: short tournaments. 2018 Jun–Jul, 2022 Nov–Dec.
    "world_cup": {
        "default": ((6, 1), (7, 31)),
        2022: ((11, 15), (12, 20)),
    },
}


class ESPNAdapter(SourceAdapter):
    name = "espn"
    trust_level = "medium"  # public aggregator → medium trust (ML-A routing)

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher()

    def supports(self, competition_key: str) -> bool:
        comp = COMPETITIONS.get(competition_key)
        return bool(comp and comp.espn_league)

    def _league(self, competition_key: str) -> str:
        comp = COMPETITIONS[competition_key]
        if not comp.espn_league:
            raise ValueError(f"ESPN does not map competition {competition_key!r}")
        return comp.espn_league

    def health(self) -> bool:
        try:
            self.fetcher.get_json(
                _BASE.format(league="bra.1"), params={"dates": "20221102"}
            )
            return True
        except FetchError:
            return False

    # --- date windows ----------------------------------------------------

    def _dates(self, competition_key: str, season: str) -> Iterator[date]:
        year = int(season[:4])
        spec = _SEASON_WINDOWS.get(competition_key, {})
        win = spec.get(year) or spec.get("default")
        if win is None:
            start, end = date(year, 1, 1), date(year, 12, 31)
            yield from _daterange(start, end)
            return
        if len(win) == 5:  # spills into the following year
            (sm, sd), (em, ed), y2, (m3, d3), (m4, d4) = win
            yield from _daterange(date(year, sm, sd), date(year, em, ed))
            yield from _daterange(date(y2, m3, d3), date(y2, m4, d4))
        else:
            (sm, sd), (em, ed) = win
            yield from _daterange(date(year, sm, sd), date(year, em, ed))

    # --- fetch -----------------------------------------------------------

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        league = self._league(competition_key)
        year = int(season[:4])
        url = _BASE.format(league=league)
        seen_ids: set[str] = set()
        for day in self._dates(competition_key, season):
            payload = self.fetcher.get_json(url, params={"dates": day.strftime("%Y%m%d")})
            for event in payload.get("events", []):
                # ESPN returns the season the event belongs to; trust it so
                # window edges never mis-bucket a match.
                ev_year = (event.get("season") or {}).get("year")
                if ev_year is not None and int(ev_year) != year:
                    continue
                eid = str(event.get("id"))
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                yield RawArtifact(
                    source=self.name,
                    provider="espn-scoreboard-v1",
                    entity_type="fixture",
                    external_id=f"espn-{eid}",
                    competition_key=competition_key,
                    season=season,
                    url=f"{url}?dates={day.strftime('%Y%m%d')}",
                    method="api",
                    retrieved_at=_now(),
                    raw=event,
                    trust_level=self.trust_level,
                    source_type="historical",
                    license_note="ESPN public scoreboard API; research use",
                )


def _daterange(start: date, end: date) -> Iterator[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
