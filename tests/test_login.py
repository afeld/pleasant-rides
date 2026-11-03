from pleasant_rides.login import is_allowed


def test_allowed_email():
    assert is_allowed("a@example.com", ["a@example.com"])


def test_ignores_case():
    assert is_allowed("A@Example.com", ["a@example.COM"])


def test_other_email():
    assert not is_allowed("b@example.com", ["a@example.com"])


def test_no_email():
    assert not is_allowed(None, ["a@example.com"])


def test_empty_allowlist():
    assert not is_allowed("a@example.com", [])
