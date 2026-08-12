"""Regression coverage: load_dataset() must not silently degrade every
record's .features to {} when projection.jsonl is missing — it should
still return a usable (degraded) dataset, but make the degradation
observable (log warning + ops ticket) instead of silent."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from atlas.intelligence.historical import load_dataset


def _write_matches(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_load_dataset_without_projection_file_logs_warning(caplog):
    with tempfile.TemporaryDirectory() as tmp:
        matches_path = Path(tmp) / "matches.jsonl"
        _write_matches(matches_path, [
            {
                "uid": "m1", "competition": "premier_league", "season": "2026",
                "kickoff_at": "2026-01-01T15:00:00Z", "home": "arsenal", "away": "chelsea",
                "home_score": 1, "away_score": 0, "label": "HOME_WIN", "sources": ["espn"],
            },
        ])
        load_dataset.cache_clear()
        with caplog.at_level(logging.WARNING, logger="atlas.intelligence.historical"):
            dataset = load_dataset(str(matches_path))
        assert any(
            "atlas_historical_projection_missing" in record.message
            for record in caplog.records
        )
        # Still usable — degraded (empty features), not a crash.
        assert len(dataset.records) == 1
        assert dataset.records[0].features == {}


def test_load_dataset_with_projection_file_present_no_warning(caplog):
    with tempfile.TemporaryDirectory() as tmp:
        matches_path = Path(tmp) / "matches.jsonl"
        projection_path = Path(tmp) / "projection.jsonl"
        _write_matches(matches_path, [
            {
                "uid": "m1", "competition": "premier_league", "season": "2026",
                "kickoff_at": "2026-01-01T15:00:00Z", "home": "arsenal", "away": "chelsea",
                "home_score": 1, "away_score": 0, "label": "HOME_WIN", "sources": ["espn"],
            },
        ])
        _write_matches(projection_path, [
            {"uid": "m1", "features": {"elo_difference": 0.2}},
        ])
        load_dataset.cache_clear()
        with caplog.at_level(logging.WARNING, logger="atlas.intelligence.historical"):
            dataset = load_dataset(str(matches_path))
        assert not any(
            "atlas_historical_projection_missing" in record.message
            for record in caplog.records
        )
        assert dataset.records[0].features == {"elo_difference": 0.2}
