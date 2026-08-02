"""Football-Data.co.uk adapter (multi-source primary, European leagues).

Football-Data publishes per-season CSVs with full results + odds. It is
**high trust** but **covers European leagues only** — no Brazilian Série A,
no Libertadores, no World Cup (verified ML-B). So `supports()` is true only
for the competitions it actually carries; for the scheduler's South-American
plan it correctly contributes nothing rather than fabricating coverage. It is
wired so that for a European competition it corroborates ESPN, exercising the
cross-source reconciliation + source-confidence path.

CSV: https://www.football-data.co.uk/mmz4281/{YYYY}/{DIV}.csv
season label "2021-2022" → file token "2122".
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_DIV = {
    "premier_league": "E0",
    "la_liga": "SP1",
}

_BASE = "https://www.football-data.co.uk/mmz4281/{token}/{div}.csv"


def _season_token(season: str) -> str | None:
    """'2021-2022' → '2122'. Single-year labels are rejected (ambiguous)."""
    if "-" not in season:
        return None
    a, b = season.split("-", 1)
    if len(a) == 4 and len(b) == 4:
        return a[2:] + b[2:]
    return None


class FootballDataAdapter(SourceAdapter):
    name = "football_data"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher()

    def supports(self, competition_key: str) -> bool:
        return competition_key in _DIV

    def health(self) -> bool:
        try:
            self._get_csv(_BASE.format(token="2122", div="E0"))
            return True
        except FetchError:
            return False

    def _get_csv(self, url: str) -> str:
        if self.fetcher._session is None:  # noqa: SLF001 - intentional reuse of session
            raise FetchError("requests not installed")
        resp = self.fetcher._session.get(url, timeout=self.fetcher.config.request_timeout_s,
                                         headers={"User-Agent": self.fetcher._ua()})  # noqa: SLF001
        if resp.status_code >= 400:
            raise FetchError(f"football-data status {resp.status_code}")
        return resp.text

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        token = _season_token(season)
        div = _DIV.get(competition_key)
        if not token or not div:
            return
        url = _BASE.format(token=token, div=div)
        text = self._get_csv(url)
        reader = csv.DictReader(io.StringIO(text))
        for i, row in enumerate(reader):
            home, away = row.get("HomeTeam"), row.get("AwayTeam")
            if not home or not away:
                continue
            ext = f"fd-{token}-{div}-{i:04d}"
            yield RawArtifact(
                source=self.name, provider="football-data-csv-v1", entity_type="fixture",
                external_id=ext, competition_key=competition_key, season=season,
                url=url, method="file", retrieved_at=_now(), raw=row,
                trust_level=self.trust_level, source_type="historical",
                license_note="football-data.co.uk free historical CSV",
            )


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_fd_date(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            continue
    return None
