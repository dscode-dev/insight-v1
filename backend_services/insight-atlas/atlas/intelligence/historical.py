"""Read-only access to certified historical matches and projections."""

from __future__ import annotations

import json
import logging
import statistics
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from atlas.ops_emitter import emitter as ops

logger = logging.getLogger(__name__)

INTELLIGENCE_NAMESPACE = UUID("3e26e2e7-c729-4bd2-a8bc-cce46a115aa2")
COMPETITION_ALIASES = {
    "brasileirao": "brasileirao_serie_a",
    "brasileirao_serie_a": "brasileirao_serie_a",
    "brazilian_serie_a": "brasileirao_serie_a",
    "sul_americana": "sudamericana",
    "copa_sul_americana": "sudamericana",
    "copa_sudamericana": "sudamericana",
    "champions_league": "champions_league",
    "uefa_champions_league": "champions_league",
    "europa_league": "europa_league",
    "uefa_europa_league": "europa_league",
    "premier_league": "premier_league",
    "la_liga": "la_liga",
    "serie_a": "serie_a",
    "bundesliga": "bundesliga",
    "ligue_1": "ligue_1",
    "libertadores": "libertadores",
    "copa_libertadores": "libertadores",
    "world_cup": "world_cup",
    "fifa_world_cup": "world_cup",
    "copa_america": "copa_america",
    "euro": "euro",
    "uefa_euro": "euro",
}


def stable_id(*parts: object) -> UUID:
    return uuid5(INTELLIGENCE_NAMESPACE, "|".join(str(part) for part in parts))


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("historical timestamp must be timezone-aware")
    return parsed


def normalize_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (value or "").strip().lower())
    chars = []
    last_sep = False
    for char in decomposed:
        if unicodedata.combining(char):
            continue
        if char.isalnum() and ord(char) < 128:
            chars.append(char)
            last_sep = False
        elif not last_sep:
            chars.append("_")
            last_sep = True
    return "".join(chars).strip("_")


def normalize_competition(value: str) -> str:
    key = normalize_key(value)
    return COMPETITION_ALIASES.get(key, key)


@dataclass(frozen=True, slots=True)
class HistoricalRecord:
    uid: str
    competition: str
    season: str
    kickoff_at: datetime
    home: str
    away: str
    home_score: int
    away_score: int
    label: str
    sources: tuple[str, ...]
    features: dict[str, float]

    @property
    def total_goals(self) -> int:
        return self.home_score + self.away_score

    @property
    def has_odds(self) -> bool:
        return float(self.features.get("odds_available", 0.0)) > 0


@dataclass(frozen=True, slots=True)
class HistoricalScope:
    competition: str
    year: int | None = None
    season: str | None = None

    @property
    def key(self) -> str:
        return f"{self.competition}:{self.year or '*'}:{self.season or '*'}"


class HistoricalDataset:
    def __init__(self, records: Iterable[HistoricalRecord]) -> None:
        self.records = tuple(
            sorted(records, key=lambda row: (row.kickoff_at, row.uid))
        )

    def select(self, scope: HistoricalScope) -> list[HistoricalRecord]:
        competition = normalize_competition(scope.competition)
        return [
            row
            for row in self.records
            if normalize_competition(row.competition) == competition
            and (scope.year is None or row.kickoff_at.year == scope.year)
            and (scope.season is None or row.season == scope.season)
        ]


@lru_cache(maxsize=4)
def load_dataset(matches_path: str, projection_path: str | None = None) -> HistoricalDataset:
    matches_file = Path(matches_path)
    projection_file = (
        Path(projection_path)
        if projection_path
        else matches_file.with_name("projection.jsonl")
    )
    projections: dict[str, dict[str, Any]] = {}
    if projection_file.exists():
        for row in _jsonl(projection_file):
            projections[str(row.get("uid"))] = row
    else:
        # Every HistoricalRecord.features silently degrades to {} without
        # this file — the whole similarity engine (v1 AND v2) would run
        # on empty/default signals with no error anywhere. Make the
        # degradation OBSERVABLE instead of silent; still return the
        # (degraded) dataset rather than hard-fail every intelligence
        # request over a missing side file.
        logger.warning(
            "atlas_historical_projection_missing",
            extra={"matches_path": matches_path, "projection_path": str(projection_file)},
        )
        ops.open_ticket(
            "historical_projection_missing",
            severity="ERROR",
            dataset=matches_path,
            impact="every HistoricalRecord.features is empty — similarity engine runs on defaults only",
            recommendation=f"generate {projection_file} (see scripts/atlas_similarity_dataset_build.py)",
            dedup_key=f"atlas:historical:projection_missing:{matches_path}",
        )
    records = []
    for match in _jsonl(matches_file):
        uid = str(match.get("uid"))
        projected = projections.get(uid, {})
        raw_sources = match.get("sources") or [match.get("selected_source") or "unknown"]
        records.append(
            HistoricalRecord(
                uid=uid,
                competition=str(match.get("competition") or ""),
                season=str(match.get("season") or ""),
                kickoff_at=parse_time(
                    str(match.get("kickoff_at") or match.get("scheduled_at"))
                ),
                home=str(match.get("home") or ""),
                away=str(match.get("away") or ""),
                home_score=int(match.get("home_score") or 0),
                away_score=int(match.get("away_score") or 0),
                label=str(match.get("label") or ""),
                sources=tuple(str(source) for source in raw_sources if source),
                features={
                    str(key): float(value)
                    for key, value in (projected.get("features") or {}).items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                },
            )
        )
    return HistoricalDataset(records)


def summarize(rows: list[HistoricalRecord]) -> dict[str, Any]:
    n = len(rows)
    labels = {
        label: sum(row.label == label for row in rows)
        for label in ("HOME_WIN", "DRAW", "AWAY_WIN")
    }
    goals = [row.total_goals for row in rows]
    odds = [row for row in rows if row.has_odds]
    sources = sorted({source for row in rows for source in row.sources})
    return {
        "sample_size": n,
        "draw_rate": labels["DRAW"] / n if n else 0.0,
        "home_win_rate": labels["HOME_WIN"] / n if n else 0.0,
        "away_win_rate": labels["AWAY_WIN"] / n if n else 0.0,
        "goals_per_match": sum(goals) / n if n else 0.0,
        "goal_volatility": statistics.pstdev(goals) if len(goals) > 1 else 0.0,
        "odds_coverage": len(odds) / n if n else 0.0,
        "source_count": len(sources),
        "sources": sources,
    }


def mean_feature(rows: list[HistoricalRecord], name: str) -> float:
    values = [row.features[name] for row in rows if name in row.features]
    return sum(values) / len(values) if values else 0.0


def _jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)
