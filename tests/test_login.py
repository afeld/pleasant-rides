import pytest

from pleasant_rides import login


def test_signed_in_without_require_login(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REQUIRE_LOGIN", raising=False)
    assert login.signed_in()


def test_not_signed_in_when_sign_in_is_not_set_up(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REQUIRE_LOGIN", "1")
    monkeypatch.setattr(login, "_auth_configured", lambda: False)
    assert not login.signed_in()
