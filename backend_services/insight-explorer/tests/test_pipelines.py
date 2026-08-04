import pytest

from explorer.pipelines.models import Pipeline, PipelineSource
from explorer.pipelines.store import PipelineNotFound, PipelineStore


def test_create_and_get_roundtrip(tmp_path):
    store = PipelineStore(tmp_path)
    p = Pipeline(name="Brasileirão enrichment", sources=[PipelineSource("espn", weight=1, priority=1)],
                 competitions=["brasileirao_serie_a"], themes=["fixtures"])
    created = store.create(p)
    assert created.created_at and created.updated_at
    fetched = store.get(created.pipeline_id)
    assert fetched.name == "Brasileirão enrichment"
    assert fetched.sources[0].name == "espn"
    assert fetched.version == 1


def test_list_returns_all_pipelines(tmp_path):
    store = PipelineStore(tmp_path)
    store.create(Pipeline(name="A"))
    store.create(Pipeline(name="B"))
    assert {p.name for p in store.list()} == {"A", "B"}


def test_update_bumps_version_and_preserves_id(tmp_path):
    store = PipelineStore(tmp_path)
    created = store.create(Pipeline(name="A", enabled=True))
    updated = store.update(created.pipeline_id, name="A renamed", enabled=False)
    assert updated.pipeline_id == created.pipeline_id
    assert updated.name == "A renamed"
    assert updated.enabled is False
    assert updated.version == 2


def test_delete_removes_pipeline(tmp_path):
    store = PipelineStore(tmp_path)
    created = store.create(Pipeline(name="A"))
    store.delete(created.pipeline_id)
    with pytest.raises(PipelineNotFound):
        store.get(created.pipeline_id)


def test_duplicate_creates_new_id_and_links_revision_of(tmp_path):
    store = PipelineStore(tmp_path)
    created = store.create(Pipeline(name="A", competitions=["brasileirao_serie_a"]))
    clone = store.duplicate(created.pipeline_id)
    assert clone.pipeline_id != created.pipeline_id
    assert clone.revision_of == created.pipeline_id
    assert clone.competitions == ["brasileirao_serie_a"]
    assert clone.name == "A (copy)"


def test_get_unknown_pipeline_raises(tmp_path):
    store = PipelineStore(tmp_path)
    with pytest.raises(PipelineNotFound):
        store.get("does-not-exist")
