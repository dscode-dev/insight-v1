"""Test helpers: a realistic ESPN raw event + a network-free FakeAdapter.

Imported bare (`from _helpers import ...`) so it never collides with another
project's `tests` package on a shared rootdir.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

from explorer.adapters.base import RawArtifact


def make_espn_event(
    event_id: str = "630801",
    home: str = "América Mineiro",
    away: str = "Internacional",
    home_abbr: str = "AMG",
    away_abbr: str = "INT",
    home_score: str | None = "1",
    away_score: str | None = "0",
    status_name: str = "STATUS_FULL_TIME",
    status_detail: str = "FT",
    date: str = "2022-11-02T19:00Z",
    season_year: int = 2022,
    venue: str | None = "Estádio Raimundo Sampaio",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "date": date,
        "name": f"{away} at {home}",
        "season": {"year": season_year, "slug": f"{season_year}-brasileiro-serie-a"},
        "competitions": [
            {
                "id": event_id,
                "venue": {"fullName": venue} if venue else {},
                "status": {"type": {"name": status_name, "detail": status_detail,
                                    "completed": status_name == "STATUS_FULL_TIME"}},
                "competitors": [
                    {"homeAway": "home", "score": home_score,
                     "team": {"id": "6154", "displayName": home, "abbreviation": home_abbr}},
                    {"homeAway": "away", "score": away_score,
                     "team": {"id": "1936", "displayName": away, "abbreviation": away_abbr}},
                ],
            }
        ],
    }


def make_artifact(event: dict[str, Any], season: str = "2022") -> RawArtifact:
    return RawArtifact(
        source="espn", provider="espn-scoreboard-v1", entity_type="fixture",
        external_id=f"espn-{event['id']}", competition_key="brasileirao_serie_a",
        season=season, url="https://site.api.espn.com/...?dates=20221102", method="api",
        retrieved_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), raw=event,
        trust_level="medium", source_type="historical", license_note="ESPN")


class FakeAdapter:
    name = "espn"
    trust_level = "medium"

    def __init__(self, artifacts: list[RawArtifact], healthy: bool = True) -> None:
        self._artifacts = artifacts
        self._healthy = healthy

    def supports(self, competition_key: str) -> bool:
        return competition_key == "brasileirao_serie_a"

    def health(self) -> bool:
        return self._healthy

    def fetch_season(self, competition_key: str, season: str) -> Iterator[RawArtifact]:
        yield from self._artifacts


class FakeCrewDown:
    """Crew whose local Qwen is unreachable (drives the degrade-with-ticket path)."""

    backend = "qwen-direct"

    def health(self) -> bool:
        return False

    def ask(self, *a: Any, **k: Any) -> Any:  # pragma: no cover - never reached when down
        from explorer.ai.runtime import AIRuntimeUnavailable

        raise AIRuntimeUnavailable("down")


def sample_artifacts() -> list[RawArtifact]:
    return [
        make_artifact(make_espn_event()),
        make_artifact(make_espn_event(event_id="630802", home="Flamengo", away="Palmeiras",
                                      home_abbr="FLA", away_abbr="PAL", home_score="2",
                                      away_score="1")),
    ]
