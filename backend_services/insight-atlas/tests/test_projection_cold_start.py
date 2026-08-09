"""Cold-start neutrality + leakage safety in HistoricalProjectionV3.

`scripts/atlas_similarity_dataset_build.py` feeds these features into the
historical similarity corpus, where they are compared against LIVE values
from `atlas/strength/formulas.py`. The two paths must agree on what "no
history yet" looks like, or a new team's live query is structurally
distant from every cold-start historical record.

Before the fix, an empty history window produced attack_strength 0.0
(worst attack in the league) AND defense_strength ≈ 5.4 (best defense in
the league) simultaneously — the same team at both extremes, purely from
absence of data — while the live path returned 1.0 for both.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("numpy")

from atlas.outcome.projection import HistoricalMatch
from atlas.outcome.projection_v3 import HistoricalProjectionV3
from atlas.strength import formulas as f

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _match(uid, *, day, home, away, home_score, away_score):
    return HistoricalMatch(
        uid=uid,
        kickoff_at=START + timedelta(days=day),
        competition="premier_league",
        season="2026",
        home=home,
        away=away,
        home_score=home_score,
        away_score=away_score,
    )


def test_cold_start_strength_is_neutral_and_matches_the_live_path():
    row = HistoricalProjectionV3().project(
        [_match("first", day=0, home="novato", away="outro", home_score=1, away_score=1)]
    )[0]

    assert row.features["home_attack_strength"] == 1.0
    assert row.features["home_defense_strength"] == 1.0
    # The live engine's neutral for the same situation.
    assert row.features["home_attack_strength"] == f.attack_strength([], 1.35)
    assert row.features["home_defense_strength"] == f.defense_strength([], 1.35)


def test_cold_start_is_not_simultaneously_worst_attack_and_best_defense():
    row = HistoricalProjectionV3().project(
        [_match("first", day=0, home="novato", away="outro", home_score=0, away_score=0)]
    )[0]
    attack = row.features["home_attack_strength"]
    defense = row.features["home_defense_strength"]
    assert attack == defense, (
        "with no history at all, attack and defense must be equally unknown"
    )


def test_genuine_zero_scoring_is_still_zero_attack():
    """The fix must only change the EMPTY case — a team that actually
    played and scored nothing still has a real 0.0 attack."""
    matches = [
        _match(f"m{i}", day=i, home="fraco", away=f"op{i}", home_score=0, away_score=2)
        for i in range(6)
    ]
    rows = {r.uid: r for r in HistoricalProjectionV3().project(matches)}
    assert rows["m5"].features["home_attack_strength"] == 0.0


def test_features_never_leak_the_match_being_projected():
    """Walk-forward invariant: a match's own result must not appear in
    its own features."""
    matches = [
        _match(f"m{i}", day=i, home="arsenal", away=f"op{i}", home_score=0, away_score=0)
        for i in range(10)
    ]
    matches.append(
        _match("TARGET", day=50, home="arsenal", away="chelsea", home_score=7, away_score=0)
    )
    rows = {r.uid: r for r in HistoricalProjectionV3().project(matches)}
    target = rows["TARGET"].features

    # Arsenal scored 0 in every strictly-prior match; the 7-0 is this
    # match's OWN result and must be invisible here.
    assert target["home_goals_for_5"] == 0.0
    assert target["home_attack_strength"] == 0.0


def test_same_kickoff_instant_matches_do_not_leak_into_each_other():
    """Matches sharing a kickoff are projected as one batch, then
    recorded — neither may see the other's result."""
    matches = [
        _match("a", day=0, home="t1", away="t2", home_score=5, away_score=0),
        _match("b", day=0, home="t3", away="t4", home_score=5, away_score=0),
    ]
    rows = {r.uid: r for r in HistoricalProjectionV3().project(matches)}
    # Both are cold-start: the competition goal rate must not yet
    # include either match's goals.
    assert rows["a"].features["home_attack_strength"] == 1.0
    assert rows["b"].features["home_attack_strength"] == 1.0
