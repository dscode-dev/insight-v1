import json

from _helpers import make_artifact, make_espn_event

from explorer.datalake.lake import DataLake
from explorer.jobs.reconcile import reconcile
from explorer.jobs.runner import JobRunner
from explorer.normalizers.football_data import normalize as fd_normalize
from explorer.normalizers.registry import normalize_artifact
from explorer.scheduler import PLAN, Scheduler
from explorer.validators.schema import validate_envelope


def test_plan_order_matches_spec():
    assert PLAN[0] == ("brasileirao_serie_a", "2020")
    assert PLAN[4] == ("brasileirao_serie_a", "2024")
    assert PLAN[5] == ("libertadores", "2020")
    assert PLAN[-2:] == (("world_cup", "2018"), ("world_cup", "2022"))
    assert len(PLAN) == 12


def test_normalizer_registry_dispatches_by_source():
    env = normalize_artifact(make_artifact(make_espn_event()))
    assert env["source"] == "espn"
    assert validate_envelope(env) == []


def test_football_data_normalizer_produces_valid_envelope():
    from explorer.adapters.base import RawArtifact

    row = {"Date": "20/04/2022", "HomeTeam": "Man City", "AwayTeam": "Liverpool",
           "FTHG": "2", "FTAG": "1", "FTR": "H", "HTHG": "1", "HTAG": "0"}
    art = RawArtifact(source="football_data", provider="football-data-csv-v1",
                      entity_type="fixture", external_id="fd-2122-E0-0001",
                      competition_key="premier_league", season="2021-2022",
                      url="https://x/E0.csv", method="file", retrieved_at="2026-06-13T00:00:00Z",
                      raw=row, trust_level="high", source_type="historical")
    env = fd_normalize(art)
    assert validate_envelope(env) == []
    assert env["payload"]["home_team"]["club_id"] == "manchester_city"
    assert env["payload"]["score"] == {"home": 2, "away": 1, "halftime_home": 1, "halftime_away": 0}


def _seed_two_sources(lake, competition="premier_league", season="2021-2022"):
    # same match, both sources agree
    base = {"schema_version": "explorer.envelope.v1", "entity_type": "fixture",
            "competition": {"competition_key": competition}, "season": season,
            "canonical_match_id": None, "captured_at": "2026-06-13T00:00:00Z",
            "provenance": {"url": "x", "retrieved_at": "2026-06-13T00:00:00Z", "method": "api"}}
    payload = {"external_fixture_id": "m1", "scheduled_at": "2022-04-20T00:00:00Z",
               "status": "finished",
               "home_team": {"name": "Man City", "club_id": "manchester_city"},
               "away_team": {"name": "Liverpool", "club_id": "liverpool"},
               "competition_key": competition, "season": season,
               "score": {"home": 2, "away": 1}}
    for src, trust, conf in (("espn", "medium", 0.9), ("football_data", "high", 0.92)):
        env = {**base, "source": src, "provider": f"{src}-v1", "source_type": "historical",
               "trust_level": trust, "confidence": conf, "external_id": f"{src}-m1",
               "payload": payload}
        lake.append("validated", competition, season, src, "fixture", [env])


def test_reconcile_records_source_agreement(tmp_path):
    lake = DataLake(tmp_path)
    _seed_two_sources(lake)
    summary = reconcile("premier_league", "2021-2022", ["espn", "football_data"], lake)
    assert summary["total_matches"] == 1
    assert summary["multi_source_matches"] == 1
    assert summary["agreements"] == 1
    assert summary["mean_confidence"] > 0.9  # corroboration bonus
    report = tmp_path / "reports" / "reconciliation" / "premier_league" / "2021-2022" / "2021-2022.json"
    assert report.exists()


def test_scheduler_persists_and_resumes(tmp_path):
    lake = DataLake(tmp_path)
    sched = Scheduler(lake=lake, use_ai=False, plan=(("brasileirao_serie_a", "2020"),))
    # simulate completing the only task
    sched.state.completed.append(["brasileirao_serie_a", "2020"])
    sched._persist()
    # a fresh scheduler over the same lake resumes with the task already done
    sched2 = Scheduler(lake=lake, use_ai=False, plan=(("brasileirao_serie_a", "2020"),))
    assert sched2.state.is_done(("brasileirao_serie_a", "2020"))
    assert sched2.run_pending() is False  # nothing left → resume-safe
    state = json.loads((tmp_path / "reports" / "scheduler_state.json").read_text())
    assert ["brasileirao_serie_a", "2020"] in state["completed"]


def test_multi_source_runs_supporting_adapters(tmp_path, sample_artifacts):
    from _helpers import FakeAdapter

    lake = DataLake(tmp_path)
    runner = JobRunner(lake=lake, use_ai=False)
    from explorer.jobs.multi import run_multi_source

    result = run_multi_source("brasileirao_serie_a", "2022", runner=runner,
                              registry=[FakeAdapter(sample_artifacts)])
    assert result["competition"] == "brasileirao_serie_a"
    assert "espn" in result["contributing_sources"]
    assert result["reconciliation"]["total_matches"] >= 1
