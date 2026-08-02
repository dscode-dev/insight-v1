import json

from atlas.intelligence_workspace import analyze, compare_models, knowledge


def _dataset(tmp_path):
    path = tmp_path / "matches.jsonl"
    rows = [
        {
            "home": "flamengo", "away": "palmeiras",
            "home_score": 2 if i % 3 else 1, "away_score": 1,
            "competition": "brasileirao_serie_a", "season": "2024",
            "source": "espn", "scheduled_at": f"2024-01-{i + 1:02d}T00:00:00Z",
        }
        for i in range(20)
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_analysis_is_deterministic_statistical_intelligence(tmp_path):
    report = analyze(str(_dataset(tmp_path)), "competition", "brasileirao_serie_a")
    assert report["context"]["sample_size"] == 20
    assert report["guardrails"] == {
        "predictions": False, "betting": False, "recommendations": False,
        "llm": False, "publication": False,
    }
    assert report["confidence"]["uncertainty"] > 0
    assert report["regime_intelligence"]["regime_id"] == "league"
    assert report["regime_intelligence"]["candidate"] == "outcome_league_v1"
    assert report["regime_intelligence"]["activated"] is False
    assert report["tendencies"]


def test_model_comparison_marks_v4_and_regimes_unpromoted():
    models = compare_models()["models"]
    assert models["outcome_v3"]["holdout"] == 0.5423
    assert models["outcome_v4"]["status"] == "candidate_unpromoted"
    assert models["outcome_league_v1"]["status"] == "candidate_unpromoted"


def test_knowledge_answers_missing_and_improvements(tmp_path):
    body = knowledge(str(_dataset(tmp_path)))
    assert "missing odds" in body["missing"]
    assert "increase odds coverage" in body["should_improve"]
