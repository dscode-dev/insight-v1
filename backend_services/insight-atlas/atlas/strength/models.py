"""Value objects for the team-strength engine — plain dataclasses, no ORM.

ORM rows live in `atlas.registry.models` (TeamStrengthStateRow,
TeamStandingsStateRow, CompetitionSeasonStateRow, HeadToHeadStateRow,
StrengthProcessedMatchRow), same split `atlas/odds/models.py` (OddsTick)
vs. `atlas/registry/models.py` (OddsTickRow) already uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One finished match, as read from Explorer's validated lake — the
    only input `StrengthRepository.record_result` needs."""

    uid: str
    competition: str
    season: str
    kickoff_at: datetime
    home: str
    away: str
    home_score: int
    away_score: int


@dataclass(frozen=True, slots=True)
class TeamStrengthFeatures:
    """The live team-strength signals for one upcoming (home, away)
    matchup — everything `AtlasIntelligenceOrchestrator._runtime_query`
    needs, pre-computed and unit-scaled where the similarity engine
    expects it (see `atlas/strength/formulas.py` for the scaling rules).

    Optional fields are None when there isn't enough data yet (cold
    start, first meeting, season just started) — callers must treat
    None as "omit this signal", never as zero.
    """

    elo_delta: float  # signed, bounded [-1, 1]
    home_attack_strength: float  # unit [0, 1], 0.5 = league average
    away_attack_strength: float
    home_defense_strength: float
    away_defense_strength: float
    h2h_advantage: float | None  # signed, bounded [-1, 1]
    table_position_gap: float | None  # signed, bounded [-1, 1]
    rest_advantage: float | None  # signed, bounded [-1, 1]
