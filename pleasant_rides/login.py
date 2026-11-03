"""Sign-in for deployed copies of the app, so that only invited people can spend its API keys and the public servers' capacity."""

import os
from collections.abc import Iterable

import streamlit as st


def is_allowed(email: str | None, allowed: Iterable[str]):
    """Whether `email` is on the allowlist, ignoring case."""
    return email is not None and email.lower() in {a.lower() for a in allowed}


def require_login():
    """Stops the page unless the viewer is signed in with an allowed email. Only when `REQUIRE_LOGIN` is set (as `fly.toml` does), so running locally needs no sign-in. The sign-in provider and `allowed_emails` come from `.streamlit/secrets.toml`; see "Deploying" in the README."""
    if not os.environ.get("REQUIRE_LOGIN"):
        return
    # without it, st.user doesn't even have is_logged_in, and reading a missing secrets.toml raises
    if not st.secrets.load_if_toml_exists() or "auth" not in st.secrets:
        st.error(
            "Sign-in isn't set up: `.streamlit/secrets.toml` needs an `[auth]` section."
        )
        st.stop()
    if not st.user.is_logged_in:
        st.button("Sign in with Google", on_click=st.login)
        st.stop()
    email = st.user.email
    if not is_allowed(
        email if isinstance(email, str) else None, st.secrets.get("allowed_emails", [])
    ):
        st.error(f"{email} doesn't have access. Ask Aidan for an invite.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
