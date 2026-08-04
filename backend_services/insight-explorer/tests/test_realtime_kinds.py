from explorer.realtime.kinds import handler_for
from explorer.realtime.models import SignalSource


def test_noop_handler_registered_and_captures_nothing():
    handler = handler_for("noop")
    assert handler is not None
    assert handler.poll(SignalSource(name="x"), fetcher=None) == []


def test_unknown_kind_returns_none():
    assert handler_for("not-a-real-kind") is None
