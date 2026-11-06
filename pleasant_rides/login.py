"""Sign-in for deployed copies of the app, so that only invited people can do what could make any number of requests to the providers, spending its API keys and the public servers' capacity: planning their own trips, running the benchmark, and previewing street-level photos. Anyone can see the sample trips and the bike lanes, which only ever fetch the same things, which are then cached."""

import os

import streamlit as st


def _auth_configured():
    # without it, st.user doesn't even have is_logged_in, and reading a missing secrets.toml raises
    return bool(st.secrets.load_if_toml_exists() and "auth" in st.secrets)


def signed_in():
    """Whether the viewer is signed in, or doesn't need to be, since `REQUIRE_LOGIN` isn't set (as it is in `fly.toml`), e.g. when running locally. The sign-in client comes from `.streamlit/secrets.toml`; who can sign in is its test users in Google, since it's left in Testing mode (see "Deploying" in the README)."""
    if not os.environ.get("REQUIRE_LOGIN"):
        return True
    return _auth_configured() and st.user.is_logged_in


def sign_in(reason: str):
    """A button for signing in, saying it's needed to `reason`, e.g. "plan your own trip"."""
    if not _auth_configured():
        st.error(
            "Sign-in isn't set up: `.streamlit/secrets.toml` needs an `[auth]` section."
        )
        return
    st.button(f"Sign in with Google to {reason}", type="primary", on_click=st.login)
    # Google shows its own error to anyone who isn't a test user, which can't be customized, so this is the place to say how to get access
    st.caption(
        "Access is by invitation. To get it, send Aidan the email address of the Google account you'll sign in with."
    )
