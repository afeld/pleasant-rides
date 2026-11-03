"""Cyclemate's SuperSafe routes, requested as the rider signed in with Cyclemate when there is one (see `cyclemate_login`), otherwise with the app's API key."""

import os
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from authlib.oauth2.rfc6749 import OAuth2Token
from authlib.oauth2.rfc7636 import create_s256_code_challenge

from .. import http_client
from ..models import Point
from .base import MissingAPIKey, Provider

URL = "https://api.cyclemate.club/directions/v2/"
# https://docs.cyclemate.club/api-reference/oauth
AUTHORIZE_URL = "https://api.cyclemate.club/auth/v1/oauth/authorize"
TOKEN_URL = "https://api.cyclemate.club/auth/v1/oauth/token"
# where Cyclemate sends riders back to; it has to match one registered for the client exactly, trailing slash included
DEFAULT_REDIRECT_URI = "http://localhost:8501/"

# the signed-in rider's access token for the current run of the page, set by `cyclemate_login`; a context variable, since every session shares one `Cyclemate` provider
access_token: ContextVar[str | None] = ContextVar(
    "cyclemate_access_token", default=None
)


class SignInExpired(Exception):
    """Cyclemate rejected the rider's access token. Not an `httpx.HTTPStatusError`, so it isn't remembered as a permanent failure for everyone (see `politeness.is_permanent()`)."""


class OAuthError(Exception):
    pass


class Cyclemate(Provider):
    """Requires a rider signed in with Cyclemate, or a key (request one via https://docs.cyclemate.club)."""

    name = "Cyclemate"
    api_key_var = "CYCLEMATE_API_KEY"

    def _auth_headers(self):
        token = access_token.get()
        if token:
            return {"Authorization": f"Bearer {token}"}
        try:
            return {"apikey": self.api_key}
        except MissingAPIKey:
            raise MissingAPIKey(
                f"sign in with Cyclemate, or set {self.api_key_var}"
            ) from None

    async def fetch(self, origin: Point, destination: Point):
        headers = self._auth_headers()
        async with http_client.client() as client:
            response = await client.post(
                URL,
                headers=headers,
                json={
                    "coordinates": [
                        [origin.lon, origin.lat],
                        [destination.lon, destination.lat],
                    ],
                    "profile": "cycling",
                    "supersafe": True,
                },
                timeout=60.0,
            )
        if response.status_code == 401 and "Authorization" in headers:
            raise SignInExpired("Cyclemate sign-in expired; sign in again")
        response.raise_for_status()
        route = response.json()["route"]
        if route is None:
            return []
        # GeoJSON coordinates are [lon, lat]
        points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
        return [("SuperSafe", points)]


@dataclass(frozen=True)
class OAuthClient:
    """The app's client registered with Cyclemate (by emailing them), for signing riders in with OAuth 2.1 and PKCE. Public without a secret, confidential with one."""

    client_id: str
    redirect_uri: str
    client_secret: str | None = None

    @classmethod
    def from_env(cls):
        """The client from `CYCLEMATE_CLIENT_ID` etc., or None when signing in with Cyclemate isn't set up."""
        client_id = os.environ.get("CYCLEMATE_CLIENT_ID")
        if not client_id:
            return None
        return cls(
            client_id,
            os.environ.get("CYCLEMATE_REDIRECT_URI") or DEFAULT_REDIRECT_URI,
            os.environ.get("CYCLEMATE_CLIENT_SECRET") or None,
        )

    def authorize_url(self, state: str, code_verifier: str):
        """Where to send the rider to sign in and approve the app."""
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "code_challenge": create_s256_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return str(httpx.URL(AUTHORIZE_URL, params=params))

    def exchange_code(self, code: str, code_verifier: str):
        """The rider's token, for the code Cyclemate sent them back with."""
        return self._request_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "code_verifier": code_verifier,
            }
        )

    def refresh(self, token: OAuth2Token):
        """A new token for the rider, since access tokens only last an hour. Refresh tokens rotate, so this keeps the new one when there is one."""
        data = {"grant_type": "refresh_token", "refresh_token": token["refresh_token"]}
        return OAuth2Token.from_dict(
            {"refresh_token": token["refresh_token"], **self._request_token(data)}
        )

    def _request_token(self, data: dict[str, str]):
        auth = None
        if self.client_secret:
            auth = httpx.BasicAuth(self.client_id, self.client_secret)
        else:
            data = {**data, "client_id": self.client_id}
        response = http_client.post(TOKEN_URL, data=data, auth=auth, timeout=30.0)
        if response.is_client_error:
            try:
                body = response.json()
            except ValueError:
                body = {}
            message = body.get("error_description") or body.get("error")
            raise OAuthError(message or f"HTTP {response.status_code}")
        response.raise_for_status()
        return OAuth2Token.from_dict(response.json())
