"""StatsBomb Open Data adapter — free event-level football data.

https://github.com/statsbomb/open-data, served from GitHub's raw CDN. Free
under the StatsBomb User Agreement for research and public analysis, with
attribution — the only source here that is event-level and legitimately open.

WHAT IT COVERS, AND WHAT IT DOES NOT. It is a curated archive, not a feed:
selected competitions and seasons, complete for the ones it has and absent for
the rest. So `supports()` is true for a competition only when the competition
INDEX says so, resolved at runtime from `competitions.json` rather than from a
table written here — a hardcoded map would drift the moment StatsBomb adds a
season, and drift in the direction that silently stops collecting.

Its Champions League coverage stops at 2018/2019, which matters: the five-year
historical window the platform wants is mostly outside it. It corroborates the
other sources on older matches and contributes nothing to recent ones, which is
the honest shape of the data rather than a defect.

Emits fixtures. Events and lineups are per-match files (one HTTP request each,
tens of thousands of rows) — worth having, and deliberately not started here:
that is a collection-volume decision, not an adapter detail.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from explorer.adapters.base import RawArtifact, SourceAdapter
from explorer.collectors.http import FetchError, PoliteFetcher

_RAW = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
_COMPETITIONS = f"{_RAW}/competitions.json"
_MATCHES = f"{_RAW}/matches/{{competition_id}}/{{season_id}}.json"

# StatsBomb competition_name → our competition key. Names, not ids, because
# the index is keyed by name and the ids are theirs to renumber.
_COMPETITION_NAMES: dict[str, str] = {
    "Premier League": "premier_league",
    "La Liga": "la_liga",
    "Champions League": "champions_league",
    "Copa del Rey": None,  # explicitly out of V1 scope
}


def _season_label(statsbomb_season: str) -> str:
    """'2015/2016' → '2015-2016'; a single-year season is passed through."""
    return statsbomb_season.replace("/", "-")


class StatsBombAdapter(SourceAdapter):
    name = "statsbomb"
    trust_level = "high"

    def __init__(self, fetcher: PoliteFetcher | None = None) -> None:
        self.fetcher = fetcher or PoliteFetcher(source=self.name)
        self._index: list[dict[str, Any]] | None = None

    # --- competition index -------------------------------------------------

    def _competitions(self) -> list[dict[str, Any]]:
        """Fetched once per adapter instance.

        `supports()` is called for every competition on every planning pass,
        and re-downloading the index each time would turn a cheap question
        into an HTTP request. An adapter instance lives for one run, so this
        cannot go stale within a run.
        """
        if self._index is None:
            try:
                self._index = self.fetcher.get_json(_COMPETITIONS)  # type: ignore[assignment]
            except FetchError:
                self._index = []
        return self._index or []

    def _seasons_for(self, competition_key: str) -> list[tuple[int, int, str]]:
        out: list[tuple[int, int, str]] = []
        for row in self._competitions():
            mapped = _COMPETITION_NAMES.get(str(row.get("competition_name", "")))
            if mapped != competition_key:
                continue
            cid, sid = row.get("competition_id"), row.get("season_id")
            if cid is None or sid is None:
                continue
            out.append((int(cid), int(sid), _season_label(str(row.get("season_name", "")))))
        return out

    # --- SourceAdapter -----------------------------------------------------

    def supports(self, competition_key: str) -> bool:
        return bool(self._seasons_for(competition_key))

    def health(self) -> bool:
        return bool(self._competitions())

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        wanted = [(c, s) for c, s, label in self._seasons_for(competition_key) if label == season]
        if not wanted:
            # The archive has this competition but not this season. Normal
            # coverage, not an outage — returning quietly keeps the scheduler
            # from opening a source_offline ticket for every season StatsBomb
            # never published.
            return

        for competition_id, season_id in wanted:
            url = _MATCHES.format(competition_id=competition_id, season_id=season_id)
            try:
                matches = self.fetcher.get_json(url)
            except FetchError:
                continue
            if not isinstance(matches, list):
                continue
            retrieved = _now()
            for match in matches:
                match_id = match.get("match_id")
                if match_id is None:
                    continue
                yield RawArtifact(
                    source=self.name,
                    provider="statsbomb-open-matches-v1",
                    entity_type="fixture",
                    external_id=f"sb-{match_id}",
                    competition_key=competition_key,
                    season=season,
                    url=url,
                    method="file",
                    retrieved_at=retrieved,
                    raw=match,
                    trust_level=self.trust_level,
                    source_type="historical",
                    license_note="StatsBomb Open Data — free with attribution",
                )


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
