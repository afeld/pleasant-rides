"""Sign-in for deployed copies of the app, so that only invited people can spend its API keys and the public servers' capacity."""

import os

import streamlit as st


def require_login():
    """Stops the page unless the viewer is signed in. Only when `REQUIRE_LOGIN` is set (as `fly.toml` does), so running locally needs no sign-in. The sign-in client comes from `.streamlit/secrets.toml`; who can sign in is its test users in Google, since it's left in Testing mode (see "Deploying" in the README)."""
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
        # Google shows its own error to anyone who isn't a test user, which can't be customized, so this is the place to say how to get access
        st.caption(
            "Access is by invitation. To get it, send Aidan the email address of the Google account you'll sign in with."
        )
        st.stop()
