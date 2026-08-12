"""Pure team-strength math — Elo, venue-Elo, attack/defense, derived gaps.

Fresh, live-capable implementation. Deliberately does NOT import from
`atlas/outcome/` (that package is offline/experimental training tooling,
explicitly "outside V1 scope" per ATLAS_V1_FROZEN.md) — this module backs
the LIVE similarity engine instead. Constants (home-advantage +65, base
K=20 with margin multiplier, venue K=16) mirror the proven values already
used in `atlas/outcome/projection_v3.py::HistoricalProjectionV3`, so the
two implementations agree on the underlying football math even though
they serve different paths (offline batch replay vs. live incremental
state).

Every function here is pure: no I/O, no datetime.now() (callers pass
`now`), deterministic given its inputs — matches Atlas's "deterministic,
descriptive, replayable" design constraint.
"""

from __future__ import annotations

from datetime import datetime, timezone

DEFAULT_ELO = 1500.0
DEFAULT_LEAGUE_GOAL_RATE = 1.35
HOME_ADVANTAGE = 65.0
BASE_K = 20.0
VENUE_K = 16.0
ROLLING_WINDOW = 10


def expected_home_score(home_elo: float, away_elo: float, *, home_advantage: float = HOME_ADVANTAGE) -> float:
    """Elo expected-score for the home side, home-advantage applied."""
    return 1.0 / (1.0 + 10 ** ((away_elo - (home_elo + home_advantage)) / 400.0))


def update_elo(
    home_elo: float,
    away_elo: float,
    home_score: int,
    away_score: int,
    *,
    home_advantage: float = HOME_ADVANTAGE,
    base_k: float = BASE_K,
) -> tuple[float, float]:
    """One match's Elo update. Margin-of-victory scales K (capped at a
    4-goal margin so blowouts don't dominate the rating)."""
    expected_home = expected_home_score(home_elo, away_elo, home_advantage=home_advantage)
    actual_home = 1.0 if home_score > away_score else 0.5 if home_score == away_score else 0.0
    margin = abs(home_score - away_score)
    k = base_k * (1.0 + min(margin, 4) * 0.15)
    delta = k * (actual_home - expected_home)
    return home_elo + delta, away_elo - delta


def update_venue_elo(
    home_venue_elo: float,
    away_venue_elo: float,
    home_score: int,
    away_score: int,
    *,
    k: float = VENUE_K,
) -> tuple[float, float]:
    """Venue-specific Elo: home team's home-form rating vs. away team's
    away-form rating, no home-advantage offset (the venue split already
    captures that)."""
    expected_home = 1.0 / (1.0 + 10 ** ((away_venue_elo - home_venue_elo) / 400.0))
    actual_home = 1.0 if home_score > away_score else 0.5 if home_score == away_score else 0.0
    delta = k * (actual_home - expected_home)
    return home_venue_elo + delta, away_venue_elo - delta


def elo_delta_unit(home_elo: float, away_elo: float) -> float:
    """Signed, bounded [-1, 1] — the same scale MatchSimilarityProfile's
    elo_delta field already expects."""
    return max(-1.0, min(1.0, (home_elo - away_elo) / 400.0))


def push_rolling_result(window: list[dict], goals_for: int, goals_against: int, *, maxlen: int = ROLLING_WINDOW) -> list[dict]:
    """Append one result to a team's rolling goals-for/against window,
    keeping only the most recent `maxlen` matches."""
    updated = [*window, {"gf": int(goals_for), "ga": int(goals_against)}]
    return updated[-maxlen:]


def league_goal_rate(goals: list[int], *, default: float = DEFAULT_LEAGUE_GOAL_RATE) -> float:
    """Average goals-per-team-per-match across a competition/season so
    far. Falls back to a neutral default with no observations yet."""
    return sum(goals) / len(goals) if goals else default


def goal_rate_from_totals(goal_sum: int, team_match_count: int, *, default: float = DEFAULT_LEAGUE_GOAL_RATE) -> float:
    """Same as `league_goal_rate`, computed from running totals (what's
    actually persisted — `CompetitionSeasonStateRow` stores a sum/count
    pair, not the raw per-match goal list)."""
    return goal_sum / team_match_count if team_match_count > 0 else default


def attack_strength(window: list[dict], league_rate: float) -> float:
    """Goals-for per match, normalized by the league's scoring rate.
    ~1.0 is league-average; higher is a stronger attack."""
    if not window:
        return 1.0
    scored = sum(row["gf"] for row in window) / len(window)
    return scored / max(league_rate, 0.25)


def defense_strength(window: list[dict], league_rate: float) -> float:
    """Inverse of goals-conceded per match, normalized by the league's
    scoring rate. ~1.0 is league-average; higher is a stronger defense."""
    if not window:
        return 1.0
    conceded = sum(row["ga"] for row in window) / len(window)
    return league_rate / max(conceded, 0.25)


def unit_strength_ratio(ratio: float, *, cap: float = 2.0) -> float:
    """Squash a strength ratio (typically ~0.3-2.5, 1.0=average) into
    [0, 1] for use as a UnitScore signal. 1.0 (average) maps to 0.5."""
    return max(0.0, min(1.0, ratio / cap))


def rest_days(previous_match_at: datetime | None, current_at: datetime) -> float | None:
    """Days since a team's previous match. None with no prior match.

    Naive datetimes are treated as UTC — some drivers (notably SQLite,
    used in tests; Postgres TIMESTAMPTZ round-trips tzinfo natively)
    drop tzinfo on read-back, and this must never crash the live path.
    """
    if previous_match_at is None:
        return None
    delta = (_as_utc(current_at) - _as_utc(previous_match_at)).total_seconds() / 86_400.0
    return max(0.0, delta)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def rest_advantage(home_rest_days: float | None, away_rest_days: float | None, *, cap_days: float = 14.0) -> float | None:
    """Signed, bounded [-1, 1]. Positive favors the home side (more
    rest). None when either side's rest is unknown."""
    if home_rest_days is None or away_rest_days is None:
        return None
    return max(-1.0, min(1.0, (home_rest_days - away_rest_days) / cap_days))


def h2h_advantage(home_wins: int, away_wins: int, draws: int) -> float | None:
    """Signed, bounded [-1, 1] head-to-head record. None with no prior
    meetings."""
    total = home_wins + away_wins + draws
    if total <= 0:
        return None
    return max(-1.0, min(1.0, (home_wins - away_wins) / total))


def table_position_gap(home_position: int | None, away_position: int | None, *, league_size: int = 20) -> float | None:
    """Signed, bounded [-1, 1]. Positive favors the home side (a lower
    position number = higher in the table). None when either position
    is unknown (e.g. season just started)."""
    if not home_position or not away_position:
        return None
    span = max(league_size - 1, 1)
    return max(-1.0, min(1.0, (away_position - home_position) / span))


def line_movement(opening_home_prob: float | None, closing_home_prob: float | None) -> float | None:
    """Signed, naturally bounded [-1, 1] — closing minus opening implied
    home probability. Positive means the market moved toward the home
    side between open and close. None when either snapshot is missing."""
    if opening_home_prob is None or closing_home_prob is None:
        return None
    return max(-1.0, min(1.0, closing_home_prob - opening_home_prob))
