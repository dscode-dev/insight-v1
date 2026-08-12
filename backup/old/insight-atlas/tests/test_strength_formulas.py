"""Pure-math coverage for atlas/strength/formulas.py — no DB, no I/O."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from atlas.strength import formulas as f


def test_update_elo_favorite_win_gains_less_than_underdog_win():
    # Home team is a big favorite (1800 vs 1400). A home win should move
    # the rating less than the same result would if home were the underdog.
    fav_home, fav_away = f.update_elo(1800.0, 1400.0, 2, 0)
    dog_home, _dog_away = f.update_elo(1400.0, 1800.0, 2, 0)
    assert (fav_home - 1800.0) < (dog_home - 1400.0)
    # Zero-sum: winner gains exactly what loser loses.
    assert round(fav_home - 1800.0, 6) == round(1400.0 - fav_away, 6)


def test_update_elo_draw_no_movement_when_outcome_matches_expectation():
    # away_elo == home_elo + HOME_ADVANTAGE makes expected_home exactly
    # 0.5 (home advantage exactly offsets the rating gap), so a draw is
    # the "expected" outcome and should produce zero rating movement.
    home, away = f.update_elo(1500.0, 1500.0 + f.HOME_ADVANTAGE, 1, 1)
    assert abs(home - 1500.0) < 1e-9
    assert abs(away - (1500.0 + f.HOME_ADVANTAGE)) < 1e-9


def test_update_elo_margin_scales_k():
    _, small_margin_away = f.update_elo(1500.0, 1500.0, 1, 0)
    _, big_margin_away = f.update_elo(1500.0, 1500.0, 5, 0)
    # A 5-0 blowout should move the loser's rating down more than 1-0.
    assert (1500.0 - big_margin_away) > (1500.0 - small_margin_away)


def test_elo_delta_unit_bounded_and_signed():
    assert f.elo_delta_unit(1900.0, 1500.0) == 1.0  # clipped at +1
    assert f.elo_delta_unit(1500.0, 1900.0) == -1.0  # clipped at -1
    assert f.elo_delta_unit(1500.0, 1500.0) == 0.0
    assert 0.0 < f.elo_delta_unit(1600.0, 1500.0) < 1.0


def test_push_rolling_result_keeps_only_maxlen():
    window: list[dict] = []
    for i in range(15):
        window = f.push_rolling_result(window, i, i + 1, maxlen=10)
    assert len(window) == 10
    assert window[-1] == {"gf": 14, "ga": 15}
    assert window[0] == {"gf": 5, "ga": 6}


def test_attack_defense_strength_average_team_is_one():
    league_rate = 1.35
    window = [{"gf": 1, "ga": 1}] * 5  # scores/concedes exactly the league rate... close enough
    window = [{"gf": round(league_rate), "ga": round(league_rate)}] * 5
    attack = f.attack_strength(window, league_rate)
    defense = f.defense_strength(window, league_rate)
    assert attack == round(league_rate) / league_rate
    assert defense == league_rate / round(league_rate)


def test_attack_strength_no_history_defaults_neutral():
    assert f.attack_strength([], 1.35) == 1.0
    assert f.defense_strength([], 1.35) == 1.0


def test_unit_strength_ratio_bounds():
    assert f.unit_strength_ratio(0.0) == 0.0
    assert f.unit_strength_ratio(2.0, cap=2.0) == 1.0
    assert f.unit_strength_ratio(10.0, cap=2.0) == 1.0  # clipped
    assert f.unit_strength_ratio(1.0, cap=2.0) == 0.5


def test_rest_days_none_without_prior_match():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert f.rest_days(None, now) is None
    prior = now - timedelta(days=7)
    assert f.rest_days(prior, now) == 7.0


def test_rest_advantage_signed_and_bounded():
    assert f.rest_advantage(None, 5.0) is None
    assert f.rest_advantage(5.0, None) is None
    assert f.rest_advantage(10.0, 3.0, cap_days=14.0) > 0  # home more rested
    assert f.rest_advantage(3.0, 10.0, cap_days=14.0) < 0  # away more rested
    assert f.rest_advantage(100.0, 0.0, cap_days=14.0) == 1.0  # clipped


def test_h2h_advantage_none_with_no_history():
    assert f.h2h_advantage(0, 0, 0) is None


def test_h2h_advantage_signed():
    assert f.h2h_advantage(3, 0, 0) == 1.0
    assert f.h2h_advantage(0, 3, 0) == -1.0
    assert f.h2h_advantage(1, 1, 2) == 0.0


def test_table_position_gap_none_when_unknown():
    assert f.table_position_gap(None, 5) is None
    assert f.table_position_gap(5, None) is None
    assert f.table_position_gap(0, 5) is None


def test_table_position_gap_signed():
    # Home 1st, away 20th in a 20-team league -> strongly favors home.
    assert f.table_position_gap(1, 20, league_size=20) == 1.0
    assert f.table_position_gap(20, 1, league_size=20) == -1.0
    assert f.table_position_gap(10, 10, league_size=20) == 0.0


def test_line_movement_none_when_missing():
    assert f.line_movement(None, 0.6) is None
    assert f.line_movement(0.6, None) is None


def test_line_movement_signed():
    assert round(f.line_movement(0.50, 0.60), 6) == 0.10
    assert round(f.line_movement(0.60, 0.50), 6) == -0.10


def test_league_goal_rate_default_with_no_data():
    assert f.league_goal_rate([]) == f.DEFAULT_LEAGUE_GOAL_RATE
    assert f.league_goal_rate([2, 4]) == 3.0
