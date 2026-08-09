"""Football-Data.co.uk adapter — results, match statistics and closing odds.

Football-Data publishes one CSV per division per season, free to use, no key.
A single fetch carries three different things, and the adapter now emits all
three instead of only the first:

    Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,...   → fixture
    HS,AS,HST,AST,HC,AC,HY,AY,HR,AR,...        → stats
    B365H/D/A, PSH/D/A, WHH/D/A, ...           → odds_snapshot (one per bookmaker)

WHY THAT MATTERS. Until now the whole platform could only collect fixtures:
`build_envelope` hardcoded entity_type="fixture", so an odds payload would
have been validated against the fixture schema and rejected. The contracts
for odds and stats already existed and were unreachable. This is the source
that makes them worth reaching — it is the only one in the registry that
carries all three for free, with five years of history.

COVERAGE. European domestic leagues only. No Brasileirão, no Libertadores,
no Copa do Brasil, no World Cup — `supports()` says so rather than
fabricating coverage, so the scheduler plans nothing it cannot fetch.

CSV: https://www.football-data.co.uk/mmz4281/{token}/{div}.csv
Season label "2021-2022" → file token "2122".
"""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime
from typing import Any, Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_DIV = {
    "premier_league": "E0",
    "la_liga": "SP1",
}

_BASE = "https://www.football-data.co.uk/mmz4281/{token}/{div}.csv"

# Bookmaker column prefixes → the name recorded on the odds snapshot.
#
# Max and Avg are deliberately included and deliberately NOT called bookmakers:
# they are the market's best price and its mean, which is what a consensus
# model actually wants. Recording them under a real bookmaker's name would
# attribute a derived number to a company that never offered it.
_BOOKMAKERS: dict[str, str] = {
    "B365": "bet365",
    "BW": "betway",
    "IW": "interwetten",
    "PS": "pinnacle",
    "WH": "william_hill",
    "VC": "vcbet",
    "Max": "_market_max",
    "Avg": "_market_avg",
}

# Football-Data's per-match stat columns, home/away prefixed.
_STAT_COLUMNS: dict[str, str] = {
    "S": "shots",
    "ST": "shots_on_target",
    "F": "fouls",
    "C": "corners",
    "Y": "yellow_cards",
    "R": "red_cards",
}


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
            self._get_csv(_BASE.format(token="2324", div="E0"))
            return True
        except FetchError:
            return False

    def _get_csv(self, url: str) -> str:
        return self.fetcher.get_text(url)

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        token = _season_token(season)
        div = _DIV.get(competition_key)
        if not token or not div:
            return
        url = _BASE.format(token=token, div=div)
        text = self._get_csv(url)
        reader = csv.DictReader(io.StringIO(text))
        retrieved = _now()

        for i, row in enumerate(reader):
            home, away = row.get("HomeTeam"), row.get("AwayTeam")
            if not home or not away:
                continue
            ext = f"fd-{token}-{div}-{i:04d}"
            common = {
                "source": self.name,
                "competition_key": competition_key,
                "season": season,
                "url": url,
                "method": "file",
                "retrieved_at": retrieved,
                "trust_level": self.trust_level,
                "source_type": "historical",
                "license_note": "football-data.co.uk free historical CSV",
            }

            yield RawArtifact(
                provider="football-data-csv-v1", entity_type="fixture",
                external_id=ext, raw=row, **common,
            )

            stats = _stats_payload(row)
            if stats:
                yield RawArtifact(
                    provider="football-data-stats-v1", entity_type="stats",
                    external_id=f"{ext}-stats",
                    raw={"_fixture_id": ext, **stats}, **common,
                )

            for snapshot in _odds_rows(row):
                yield RawArtifact(
                    provider="football-data-odds-v1", entity_type="odds_snapshot",
                    external_id=f"{ext}-odds-{snapshot['bookmaker']}",
                    raw={"_fixture_id": ext, "_date": row.get("Date", ""), **snapshot},
                    **common,
                )


def _stats_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """Home/away match statistics, or None when the row carries none.

    Older seasons omit the stat columns entirely. Emitting an artifact with
    every field empty would count as a collected record and inflate coverage
    with rows that say nothing.
    """
    home: dict[str, int] = {}
    away: dict[str, int] = {}
    for suffix, field_name in _STAT_COLUMNS.items():
        h, a = _int(row.get(f"H{suffix}")), _int(row.get(f"A{suffix}"))
        if h is not None:
            home[field_name] = h
        if a is not None:
            away[field_name] = a
    if not home and not away:
        return None
    return {"home": home, "away": away}


def _odds_rows(row: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One 1X2 snapshot per bookmaker that quoted all three outcomes.

    A partial quote is skipped rather than filled with nulls: a market with a
    missing outcome is not a market, and downstream a null price is
    indistinguishable from a price of zero.
    """
    for prefix, bookmaker in _BOOKMAKERS.items():
        home = _float(row.get(f"{prefix}H"))
        draw = _float(row.get(f"{prefix}D"))
        away = _float(row.get(f"{prefix}A"))
        if home is None or draw is None or away is None:
            continue
        yield {
            "bookmaker": bookmaker,
            "market": "1x2",
            "selections": [
                {"name": "home", "price": home},
                {"name": "draw", "price": draw},
                {"name": "away", "price": away},
            ],
        }


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    # A decimal odd below 1.0 pays less than the stake, which no bookmaker
    # offers — it is a parsing artefact (an empty cell read as 0.0).
    return parsed if parsed >= 1.0 else None


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_fd_date(value: str) -> str | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            continue
    return None
