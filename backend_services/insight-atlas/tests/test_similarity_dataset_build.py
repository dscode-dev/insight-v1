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
