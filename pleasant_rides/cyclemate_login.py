"""Sign-in with Cyclemate (https://docs.cyclemate.club/api-reference/oauth), after signing in to the app, so that the Cyclemate provider requests routes as the rider, against their own rate limit, rather than with the app's API key. Only when the app has a Cyclemate client (`CYCLEMATE_CLIENT_ID`; see the README)."""

import html
import os
import time

import httpx
import streamlit as st
from authlib.common.security import generate_token

from .providers import cyclemate, redact
from .providers.cyclemate import OAuthClient, OAuthError

# Cyclemate's sign-in page lasts 3 minutes and the code it sends the rider back with 10, so this leaves time to get to it
SIGN_IN_TIMEOUT_S = 15 * 60
# in `st.session_state`
_TOKEN = "cyclemate_token"
_SIGN_IN_STATE = "cyclemate_sign_in_state"

Pending = dict[str, tuple[str, float]]


@st.cache_resource
def _pending() -> Pending:
    """The sign-ins in progress: state -> (PKCE code verifier, when it started). Shared across sessions, since Cyclemate sends the rider back to a new one."""
    return {}


def start_sign_in(pending: Pending, now: float):
    """A new sign-in's state and code verifier, kept in `pending`, which is cleared of expired ones."""
    for state, (_, started) in list(pending.items()):
        if now - started > SIGN_IN_TIMEOUT_S:
            del pending[state]
    state, verifier = generate_token(32), generate_token(64)
    pending[state] = (verifier, now)
    return state, verifier


def take_verifier(pending: Pending, state: str, now: float):
    """The code verifier of the sign-in that `state` belongs to, or None if it's unknown or expired. Each can only be taken once."""
    verifier, started = pending.pop(state, (None, 0.0))
    if verifier is None or now - started > SIGN_IN_TIMEOUT_S:
        return None
    return verifier


def use_cyclemate_login():
    """Finishes a sign-in that Cyclemate sent the rider back from, refreshes their token when it's about to expire, and gives it to the Cyclemate provider for this run."""
    client = OAuthClient.from_env()
    token = None
    if client:
        _finish_sign_in(client)
        token = _fresh_token(client)
    cyclemate.access_token.set(token["access_token"] if token else None)


def _finish_sign_in(client: OAuthClient):
    params = st.query_params
    state = params.get("state")
    if not state:
        return
    code = params.get("code")
    error = params.get("error_description") or params.get("error")
    st.query_params.clear()
    verifier = take_verifier(_pending(), state, time.time())
    if error:
        st.warning(f"Didn't sign in with Cyclemate: {error}")
    elif not (code and verifier):
        st.warning("That sign-in with Cyclemate expired. Please try again.")
    else:
        try:
            st.session_state[_TOKEN] = client.exchange_code(code, verifier)
        except (OAuthError, httpx.HTTPError) as e:
            st.warning(
                redact(f"Couldn't sign in with Cyclemate ({type(e).__name__}: {e})")
            )


def _fresh_token(client: OAuthClient):
    token = st.session_state.get(_TOKEN)
    if token and token.is_expired(leeway=60):
        try:
            token = st.session_state[_TOKEN] = client.refresh(token)
        except (OAuthError, httpx.HTTPError):
            # e.g. a revoked refresh token, so they need to sign in again
            del st.session_state[_TOKEN]
            return None
    return token


def sign_in_prompt():
    """Offers to sign in with Cyclemate, or to sign out once signed in."""
    if not OAuthClient.from_env():
        return
    if st.session_state.get(_TOKEN):
        st.button(
            "Sign out of Cyclemate", on_click=lambda: st.session_state.pop(_TOKEN)
        )
        return
    with_key = bool(os.environ.get(cyclemate.Cyclemate.api_key_var or ""))
    reason = "request its routes as you" if with_key else "include its routes"
    # a plain link, so that it opens in the same tab, which Cyclemate then sends back here
    st.markdown(
        f'<a href="{html.escape(_sign_in_url())}" target="_self">Sign in with Cyclemate</a> to {reason}.',
        unsafe_allow_html=True,
    )


def _sign_in_url():
    """The link to sign in, made once per session (or once its sign-in expires), so that reruns don't each start one."""
    client = OAuthClient.from_env()
    assert client
    pending = _pending()
    now = time.time()
    state, verifier = st.session_state.get(_SIGN_IN_STATE, (None, None))
    if state not in pending or now - pending[state][1] > SIGN_IN_TIMEOUT_S:
        state, verifier = st.session_state[_SIGN_IN_STATE] = start_sign_in(pending, now)
    assert state and verifier
    return client.authorize_url(state, verifier)
