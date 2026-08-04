import pytest

from explorer.realtime.models import SignalSource
from explorer.realtime.store import SignalSourceNotFound, SignalSourceStore


def test_create_and_get_roundtrip(tmp_path):
    store = SignalSourceStore(tmp_path)
    created = store.create(SignalSource(name="NewsAPI football", kind="api", api_key="super-secret"))
    fetched = store.get(created.source_id)
    assert fetched.name == "NewsAPI football"
    assert fetched.api_key == "super-secret"  # raw store keeps it — masking is a response-layer concern


def test_to_public_dict_never_echoes_raw_key():
    source = SignalSource(name="x", api_key="super-secret")
    public = source.to_public_dict()
    assert "api_key" not in public
    assert public["api_key_set"] is True
    assert "super-secret" not in str(public)


def test_to_public_dict_reports_false_when_no_key_set():
    source = SignalSource(name="x", api_key=None)
    assert source.to_public_dict()["api_key_set"] is False


def test_list_returns_all_sources(tmp_path):
    store = SignalSourceStore(tmp_path)
    store.create(SignalSource(name="A"))
    store.create(SignalSource(name="B"))
    assert {s.name for s in store.list()} == {"A", "B"}


def test_update_preserves_api_key_when_omitted(tmp_path):
    store = SignalSourceStore(tmp_path)
    created = store.create(SignalSource(name="x", api_key="secret-1"))
    updated = store.update(created.source_id, name="renamed")
    assert updated.name == "renamed"
    assert updated.api_key == "secret-1"


def test_update_overwrites_api_key_when_explicitly_present(tmp_path):
    store = SignalSourceStore(tmp_path)
    created = store.create(SignalSource(name="x", api_key="secret-1"))
    updated = store.update(created.source_id, api_key="secret-2")
    assert updated.api_key == "secret-2"


def test_delete_removes_source(tmp_path):
    store = SignalSourceStore(tmp_path)
    created = store.create(SignalSource(name="x"))
    store.delete(created.source_id)
    with pytest.raises(SignalSourceNotFound):
        store.get(created.source_id)


def test_get_unknown_source_raises(tmp_path):
    store = SignalSourceStore(tmp_path)
    with pytest.raises(SignalSourceNotFound):
        store.get("does-not-exist")
