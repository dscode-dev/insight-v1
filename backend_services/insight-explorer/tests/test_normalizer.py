import pytest
from _helpers import make_artifact, make_espn_event

from explorer.normalizers.espn import NormalizationError, normalize
from explorer.validators.schema import validate_envelope


def test_normalizes_to_valid_envelope():
    env = normalize(make_artifact(make_espn_event()))
    assert env["schema_version"] == "explorer.envelope.v1"
    assert env["entity_type"] == "fixture"
    assert validate_envelope(env) == []


def test_resolves_team_club_ids():
    env = normalize(make_artifact(make_espn_event()))
    assert env["payload"]["home_team"]["club_id"] == "america_mineiro"
    assert env["payload"]["away_team"]["club_id"] == "internacional"


def test_status_and_score_mapping():
    env = normalize(make_artifact(make_espn_event(status_name="STATUS_FULL_TIME")))
    assert env["payload"]["status"] == "finished"
    assert env["payload"]["score"] == {"home": 1, "away": 0}

    sched = normalize(make_artifact(make_espn_event(
        status_name="STATUS_SCHEDULED", status_detail="Sched",
        home_score=None, away_score=None)))
    assert sched["payload"]["status"] == "scheduled"
    assert "score" not in sched["payload"]


def test_scheduled_at_normalized_to_seconds():
    env = normalize(make_artifact(make_espn_event(date="2022-11-02T19:00Z")))
    assert env["payload"]["scheduled_at"] == "2022-11-02T19:00:00Z"


def test_missing_competitors_raises():
    bad = make_espn_event()
    bad["competitions"][0]["competitors"] = []
    with pytest.raises(NormalizationError):
        normalize(make_artifact(bad))
