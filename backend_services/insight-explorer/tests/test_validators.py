from _helpers import make_artifact, make_espn_event

from explorer.normalizers.espn import normalize
from explorer.validators.consistency import check
from explorer.validators.dedup import deduplicate, duplication_ratio
from explorer.validators.quality import score


def _env(**kw):
    return normalize(make_artifact(make_espn_event(**kw)))


def test_consistency_clean_record():
    assert check(_env()) == []


def test_consistency_same_team():
    env = _env()
    env["payload"]["away_team"]["name"] = env["payload"]["home_team"]["name"]
    assert "same_team_both_sides" in check(env)


def test_consistency_finished_without_score():
    env = _env()
    env["payload"].pop("score", None)
    assert "finished_without_score" in check(env)


def test_consistency_implausible_score():
    env = _env()
    env["payload"]["score"]["home"] = 99
    assert "implausible_score_home" in check(env)


def test_quality_high_for_complete_record():
    sc, breakdown = score(_env())
    assert sc >= 0.9
    assert set(breakdown) >= {"home_resolved", "away_resolved", "trust"}


def test_quality_drops_when_unresolved():
    env = _env(home="Totally Unknown Club XYZ")
    sc, _ = score(env)
    assert sc < 0.9


def test_dedup_removes_by_external_id():
    a = _env()
    b = _env()  # same external_id + checksum
    c = _env(event_id="999", home="Flamengo", away="Palmeiras")
    unique, removed = deduplicate([a, b, c])
    assert removed == 1
    assert len(unique) == 2
    assert duplication_ratio(3, 1) == 1 / 3
