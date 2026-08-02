from _helpers import FakeAdapter

from explorer.api.service import ExplorerReadService
from explorer.clubs import registry_size, resolve_club
from explorer.datalake.lake import DataLake
from explorer.jobs.runner import JobRunner
from explorer.ops.quality_engine import score_dataset
from explorer.ops.review import ReviewStore


def test_registry_has_south_american_clubs():
    # ML-C Part 1: registry expansion resolves CONMEBOL clubs + nations.
    assert registry_size() >= 185
    assert resolve_club("River Plate") == "river_plate"
    assert resolve_club("Colo Colo") == "colo_colo"
    assert resolve_club("LDU Quito") == "ldu_quito"
    assert resolve_club("Atlético Junior") == "junior"
    assert resolve_club("Brazil") is not None
    assert resolve_club("Argentina") is not None


def test_quality_engine_is_deterministic():
    jobs = [{"records_collected": 100, "records_validated": 90, "records_review": 8,
             "records_rejected": 2, "duplicates_removed": 1}]
    a = score_dataset(jobs, agreement=0.9)
    b = score_dataset(jobs, agreement=0.9)
    assert a == b
    assert 0.0 <= a["quality_score"] <= 1.0
    assert a["grade"] in {"A", "B", "C", "D"}
    assert set(a["dimensions"]) == {"completeness", "validation_success", "consistency",
                                    "duplicate_cleanliness", "agreement"}


def _seed(tmp_path):
    lake = DataLake(tmp_path)
    runner = JobRunner(lake=lake, use_ai=False)
    # one resolvable + one unresolvable (forces a review record with envelope)
    from _helpers import make_artifact, make_espn_event
    arts = [make_artifact(make_espn_event()),
            make_artifact(make_espn_event(event_id="900", home="Unknown Club ZZZ",
                                          away="Internacional"))]
    runner.run(FakeAdapter(arts), "brasileirao_serie_a", "2022")
    return tmp_path


def test_entity_resolution_center(tmp_path):
    svc = ExplorerReadService(_seed(tmp_path))
    er = svc.entity_resolution()
    assert er["resolved"] >= 1
    assert er["human_reviewed"] >= 1
    assert er["registry_size"] >= 185
    assert isinstance(er["explanations"], list)


def test_review_queue_and_promote(tmp_path):
    root = _seed(tmp_path)
    rev = ReviewStore(root)
    q = rev.queue(status="pending")
    assert q, "expected a pending review record (unresolved club)"
    ext = q[0]["external_id"]
    res = rev.promote(ext)
    assert res["promoted"] == ext
    # promoted record leaves the pending queue and lands in validated/
    assert all(r["external_id"] != ext for r in rev.queue(status="pending"))
    lake = DataLake(root)
    promoted = list(lake.read("validated", res["competition"], res["season"], res["source"], "fixture"))
    assert any(e.get("external_id") == ext for e in promoted)


def test_duplicates_and_analytics(tmp_path):
    svc = ExplorerReadService(_seed(tmp_path))
    dup = svc.duplicates()
    assert "overall_duplicate_rate" in dup
    assert "fixture" in dup["by_entity_type"]
    an = svc.analytics()
    assert "brasileirao_serie_a" in an["records_per_competition"]
    assert an["totals"]["validated"] >= 1


def test_quality_datasets(tmp_path):
    svc = ExplorerReadService(_seed(tmp_path))
    q = svc.quality_datasets()
    assert 0.0 <= q["overall_quality_score"] <= 1.0
    assert q["per_competition"]
    assert q["per_dataset"]
