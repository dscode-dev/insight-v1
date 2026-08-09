"""Baseline integrity: the report must describe its own data honestly.

Two Round-4 findings, both class (a) — real bugs inside the frozen
intelligence core, fixed before the frozen regression baseline was ever
recorded (ATLAS_V1_FROZEN.md still lists that as a pending action).

1. TARGET LEAKAGE — `report_builder`/`orchestrator` filtered the
   baseline with `kickoff_at <= query.kickoff_at`, which RETAINS the
   analysed match (it is `rows[-1]`). Every downstream engine then
   described the match using that match's own result, while
   signal_engine labelled the evidence "leakage-safe form projection".
   The hierarchical memory in the SAME report already used the correct
   strict-prior policy — two halves disagreeing.

2. NON-MONOTONIC UNCERTAINTY — the score was a MEAN of heterogeneous
   deficiency components, so each additional problem grew the
   denominator and diluted the others. Strictly worse data could score
   strictly lower uncertainty.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from atlas.intelligence.historical import (
    HistoricalDataset,
    HistoricalRecord,
    HistoricalScope,
)
from atlas.intelligence.report_builder import HistoricalIntelligenceReportBuilder
from atlas.intelligence.uncertainty_engine import UncertaintyEngine

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = datetime.now(timezone.utc)


# --- 1. target leakage ------------------------------------------------------


def _record(uid, *, day, home_score, away_score, label):
    return HistoricalRecord(
        uid=uid,
        competition="premier_league",
        season="2026",
        kickoff_at=START + timedelta(days=day),
        home="a",
        away="b",
        home_score=home_score,
        away_score=away_score,
        label=label,
        sources=("espn",),
        features={},
    )


def _leaky_dataset() -> HistoricalDataset:
    """39 goalless draws, then one wildly different 5-4 home win as the
    most recent match — the one that gets analysed."""
    rows = [
        _record(f"d{i}", day=i, home_score=0, away_score=0, label="DRAW")
        for i in range(39)
    ]
    rows.append(_record("TARGET", day=100, home_score=5, away_score=4, label="HOME_WIN"))
    return HistoricalDataset(rows)


def test_analysed_match_is_excluded_from_its_own_baseline():
    report = HistoricalIntelligenceReportBuilder(_leaky_dataset()).build(
        HistoricalScope(competition="premier_league")
    )
    by_name = {s.signal_name: s for s in report.signals}

    scoring = by_name["scoring_tendency"].evidence[0]
    draws = by_name["draw_tendency"].evidence[0]

    # Ground truth over the 39 strictly-prior matches: all 0-0 draws.
    assert scoring.attributes["sample_size"] == 39, (
        "the analysed match leaked into its own baseline"
    )
    assert draws.attributes["sample_size"] == 39
    # With leakage this read "0.225 goals per match" / "97.5% draw rate".
    assert "0.000 goals" in scoring.description
    assert "100.0% draw rate" in draws.description


# --- 2. uncertainty monotonicity -------------------------------------------


def _score(**overrides) -> float:
    kwargs = dict(
        scope_key="scope",
        sample_size=200,
        odds_coverage=1.0,
        source_count=2,
        market_disagreement=0.0,
        conflicting_signals=[],
        unavailable_signals=[],
        created_at=NOW,
    )
    kwargs.update(overrides)
    return UncertaintyEngine().assess(**kwargs).uncertainty_score


def test_perfect_inputs_score_zero_uncertainty():
    assert _score() == 0.0


@pytest.mark.parametrize(
    "worse,better",
    [
        # Each pair: strictly worse data must NOT score lower.
        (dict(odds_coverage=0.0, source_count=1), dict(odds_coverage=0.0)),
        (
            dict(sample_size=80, source_count=1),
            dict(sample_size=80),
        ),
        (
            dict(sample_size=80, source_count=1, conflicting_signals=["x"]),
            dict(sample_size=80, source_count=1),
        ),
        (
            dict(sample_size=80, source_count=1, conflicting_signals=["x", "y"]),
            dict(sample_size=80, source_count=1, conflicting_signals=["x"]),
        ),
        (
            dict(sample_size=80, unavailable_signals=["a", "b"]),
            dict(sample_size=80, unavailable_signals=["a"]),
        ),
    ],
)
def test_adding_a_deficiency_never_lowers_uncertainty(worse, better):
    assert _score(**worse) >= _score(**better)


def test_score_stays_within_unit_range():
    saturated = _score(
        odds_coverage=0.0,
        sample_size=1,
        source_count=1,
        market_disagreement=1.0,
        conflicting_signals=["a", "b", "c"],
        unavailable_signals=["x", "y"],
    )
    assert 0.0 <= saturated <= 1.0


def test_more_deficiencies_still_discriminate_in_the_partial_range():
    """Monotonicity must not come at the cost of collapsing everything
    to 1.0 — partial deficiencies should still produce a gradient."""
    one = _score(sample_size=80)
    two = _score(sample_size=80, source_count=1)
    three = _score(sample_size=80, source_count=1, conflicting_signals=["x"])
    assert one < two < three < 1.0
