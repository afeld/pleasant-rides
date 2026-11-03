from pleasant_rides import cyclemate_login


def test_sign_in_attempts_expire():
    pending: dict[str, tuple[str, float]] = {}
    state, verifier = cyclemate_login.start_sign_in(pending, now=0)
    assert cyclemate_login.take_verifier(pending, state, now=60) == verifier
    # each is used once
    assert cyclemate_login.take_verifier(pending, state, now=60) is None

    state, _ = cyclemate_login.start_sign_in(pending, now=0)
    late = cyclemate_login.SIGN_IN_TIMEOUT_S + 1
    assert cyclemate_login.take_verifier(pending, state, now=late) is None
    assert cyclemate_login.take_verifier(pending, "unknown", now=0) is None
