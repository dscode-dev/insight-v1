from explorer.api.app import control_token_error


def test_controls_fail_closed_without_configured_token(monkeypatch):
    monkeypatch.delenv("EXPLORER_OPS_TOKEN", raising=False)
    assert control_token_error(None) == (503, "explorer_controls_disabled")


def test_controls_reject_invalid_token(monkeypatch):
    monkeypatch.setenv("EXPLORER_OPS_TOKEN", "expected")
    assert control_token_error("invalid") == (401, "invalid_ops_token")
    assert control_token_error("expected") is None
