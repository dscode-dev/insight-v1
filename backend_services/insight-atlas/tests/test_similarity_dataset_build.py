"""End-to-end coverage for scripts/atlas_similarity_dataset_build.py —
Explorer-shaped fixture lake in, matches.jsonl+projection.jsonl out,
readable by load_dataset() with the new v2 derived signals populated."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

pytest.importorskip("numpy")

from atlas.intelligence.historical import load_dataset
from atlas.intelligence.similarity_engine import profile_from_record
from scripts.atlas_similarity_dataset_build import build


def _fixture_line(*, external_id, home, away, home_score, away_score, scheduled_at, competition="premier_league", season="2026", sources=("espn",)):
    return json.dumps({
        "external_id": external_id,
        "season": season,
        "competition": {"competition_key": competition},
        "sources": list(sources),
        "payload": {
            "status": "finished",
            "score": {"home": home_score, "away": away_score},
            "home_team": {"club_id": home},
            "away_team": {"club_id": away},
            "scheduled_at": scheduled_at,
        },
    })


def test_build_produces_readable_dataset_with_v2_signals():
    with tempfile.TemporaryDirectory() as lake_dir, tempfile.TemporaryDirectory() as out_dir:
        lines = []
        for i in range(4):
            lines.append(_fixture_line(
                external_id=f"e{i}", home="arsenal", away="chelsea" if i % 2 == 0 else "wolves",
                home_score=2, away_score=0,
                scheduled_at=f"2026-0{1 + i}-01T15:00:00Z",
            ))
        with open(os.path.join(lake_dir, "fixtures.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")

        summary = build(lake_dir, out_dir)
        assert summary["rows"] == 4
        assert os.path.exists(os.path.join(out_dir, "matches.jsonl"))
        assert os.path.exists(os.path.join(out_dir, "projection.jsonl"))

        load_dataset.cache_clear()
        dataset = load_dataset(os.path.join(out_dir, "matches.jsonl"))
        assert len(dataset.records) == 4
        # The last (4th) Arsenal match should carry non-default attack
        # strength and elo_difference — real signal, not a cold-start
        # placeholder, since Arsenal has 3 prior wins by then.
        last = dataset.records[-1]
        assert last.features.get("home_attack_strength") is not None
        profile = profile_from_record(last)
        assert profile.elo_delta > 0.0  # Arsenal has been winning
        assert profile.home_attack_strength > 0.5  # above league-average


def _write(lake_dir, name, lines):
    source_dir = os.path.join(lake_dir, "premier_league", "2026", name, "fixture")
    os.makedirs(source_dir, exist_ok=True)
    with open(os.path.join(source_dir, "part-0001.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def test_same_match_from_three_sources_becomes_one_record():
    """Three sources describing one match produced three corpus entries.

    Each source names the match with its own id — fd-2021-SP1-0075,
    of-es.1-2020-21-0075, sb-3773477 — and the uid was derived from that id.
    The cost was not storage: project() replays in kickoff order and updates
    Elo, attack/defense and h2h as it goes, so one real match moved every
    rating three times, and similarity returned it as three separate
    neighbours.
    """
    with tempfile.TemporaryDirectory() as lake_dir, tempfile.TemporaryDirectory() as out_dir:
        # Same match, three spellings of the clock, three external ids.
        _write(lake_dir, "football_data", [_fixture_line(
            external_id="fd-2021-SP1-0075", home="barcelona", away="real_betis",
            home_score=5, away_score=2, scheduled_at="2020-11-07T00:00:00Z",
            sources=("football_data",))])
        _write(lake_dir, "openfootball", [_fixture_line(
            external_id="of-es.1-2020-21-0075", home="barcelona", away="real_betis",
            home_score=5, away_score=2, scheduled_at="2020-11-07T21:00:00Z",
            sources=("openfootball",))])
        _write(lake_dir, "statsbomb", [_fixture_line(
            external_id="sb-3773477", home="barcelona", away="real_betis",
            home_score=5, away_score=2, scheduled_at="2020-11-07T21:00:00Z",
            sources=("statsbomb",))])

        summary = build(lake_dir, out_dir)
        assert summary["read"] == 3
        assert summary["unique"] == 1
        assert summary["collapsed"] == 2
        assert summary["multi_source"] == 1
        assert summary["score_conflicts"] == 0

        with open(os.path.join(out_dir, "matches.jsonl"), encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh]
        assert len(records) == 1
        # `sources` was always a one-element list before, because the uid it
        # keyed on could only ever come from one source.
        assert records[0]["sources"] == ["football_data", "openfootball", "statsbomb"]
        # The informative kickoff wins over Football-Data's midnight
        # placeholder, independently of which source ranks higher on facts.
        assert records[0]["kickoff_at"].startswith("2020-11-07T21:00")


def test_same_pair_twice_in_one_season_stays_two_matches():
    """A Champions League side can host the same opponent in the group stage
    and again in a semi-final. Dropping the date from the key would have
    silently merged them."""
    with tempfile.TemporaryDirectory() as lake_dir, tempfile.TemporaryDirectory() as out_dir:
        _write(lake_dir, "openfootball", [
            _fixture_line(external_id="a", home="real_madrid", away="bayern",
                          home_score=1, away_score=0,
                          scheduled_at="2026-09-15T19:00:00Z",
                          competition="champions_league"),
            _fixture_line(external_id="b", home="real_madrid", away="bayern",
                          home_score=2, away_score=2,
                          scheduled_at="2027-04-20T19:00:00Z",
                          competition="champions_league"),
        ])
        summary = build(lake_dir, out_dir)
        assert summary["unique"] == 2
        assert summary["collapsed"] == 0


def test_disagreeing_scores_are_reported_not_hidden():
    with tempfile.TemporaryDirectory() as lake_dir, tempfile.TemporaryDirectory() as out_dir:
        _write(lake_dir, "football_data", [_fixture_line(
            external_id="fd-1", home="arsenal", away="chelsea",
            home_score=2, away_score=0, scheduled_at="2026-01-01T15:00:00Z")])
        _write(lake_dir, "openfootball", [_fixture_line(
            external_id="of-1", home="arsenal", away="chelsea",
            home_score=3, away_score=0, scheduled_at="2026-01-01T15:00:00Z")])

        summary = build(lake_dir, out_dir)
        assert summary["unique"] == 1
        assert summary["score_conflicts"] == 1

        with open(os.path.join(out_dir, "matches.jsonl"), encoding="utf-8") as fh:
            record = json.loads(fh.readline())
        # football_data outranks openfootball, so its score is the one kept.
        assert record["home_score"] == 2
