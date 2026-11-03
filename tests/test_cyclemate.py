import asyncio
import base64
import hashlib
from urllib.parse import parse_qs

import httpx
import pytest

from pleasant_rides.models import Point
from pleasant_rides.politeness import is_permanent
from pleasant_rides.providers import cyclemate
from pleasant_rides.providers.base import MissingAPIKey
from pleasant_rides.providers.cyclemate import Cyclemate, OAuthClient, SignInExpired

ORIGIN = Point(40.0, -74.0)
DESTINATION = Point(40.01, -74.0)
ROUTE = {"route": {"geometry": {"coordinates": [[-74.0, 40.0], [-74.0, 40.01]]}}}
TOKEN = {
    "access_token": "access-1",
    "token_type": "bearer",
    "expires_in": 3600,
    "refresh_token": "refresh-1",
    "scope": "email",
}


@pytest.fixture
def requests(monkeypatch):
    """Answers Cyclemate's HTTP requests (with `responses[path]`, a route by default), returning the list of requests made."""
    made: list[httpx.Request] = []
    responses: dict[str, httpx.Response] = {}

    def handle(request: httpx.Request):
        made.append(request)
        return responses.get(request.url.path, httpx.Response(200, json=ROUTE))

    def send(method: str, url: str, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            return client.request(method, url, **kwargs)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.setattr(
        cyclemate.http_client, "post", lambda url, **kw: send("POST", url, **kw)
    )
    made_and_responses = made, responses
    return made_and_responses


@pytest.fixture
def signed_in():
    reset = cyclemate.access_token.set("rider-token")
    yield
    cyclemate.access_token.reset(reset)


def form(request: httpx.Request):
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def test_uses_signed_in_riders_token(requests, signed_in, monkeypatch):
    monkeypatch.setenv("CYCLEMATE_API_KEY", "app-key")
    made, _ = requests
    routes = asyncio.run(Cyclemate().get_routes(ORIGIN, DESTINATION))
    (request,) = made
    assert request.headers["Authorization"] == "Bearer rider-token"
    assert "apikey" not in request.headers
    assert routes[0].points == (ORIGIN, DESTINATION)


def test_falls_back_to_api_key(requests, monkeypatch):
    monkeypatch.setenv("CYCLEMATE_API_KEY", "app-key")
    made, _ = requests
    asyncio.run(Cyclemate().get_routes(ORIGIN, DESTINATION))
    (request,) = made
    assert request.headers["apikey"] == "app-key"
    assert "Authorization" not in request.headers


def test_needs_sign_in_or_api_key(monkeypatch):
    monkeypatch.delenv("CYCLEMATE_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey, match="sign in.*CYCLEMATE_API_KEY"):
        asyncio.run(Cyclemate().get_routes(ORIGIN, DESTINATION))


def test_rejected_token_isnt_a_permanent_failure(requests, signed_in):
    _, responses = requests
    responses["/directions/v2/"] = httpx.Response(401, json={"error": "expired"})
    with pytest.raises(SignInExpired) as error:
        asyncio.run(Cyclemate().get_routes(ORIGIN, DESTINATION))
    # otherwise the route would be skipped for everyone until the app restarts
    assert not is_permanent(error.value)


def test_client_from_env(monkeypatch):
    monkeypatch.delenv("CYCLEMATE_CLIENT_ID", raising=False)
    assert OAuthClient.from_env() is None

    monkeypatch.setenv("CYCLEMATE_CLIENT_ID", "id")
    monkeypatch.delenv("CYCLEMATE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("CYCLEMATE_REDIRECT_URI", raising=False)
    assert OAuthClient.from_env() == OAuthClient("id", "http://localhost:8501/")


def test_authorize_url():
    client = OAuthClient("id", "http://localhost:8501/")
    url = httpx.URL(client.authorize_url("the-state", "the-verifier"))
    assert str(url.copy_with(query=None)) == cyclemate.AUTHORIZE_URL
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(b"the-verifier").digest())
        .rstrip(b"=")
        .decode()
    )
    assert dict(url.params) == {
        "response_type": "code",
        "client_id": "id",
        "redirect_uri": "http://localhost:8501/",
        "state": "the-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }


def test_public_client_exchanges_code(requests):
    made, responses = requests
    responses["/auth/v1/oauth/token"] = httpx.Response(200, json=TOKEN)
    token = OAuthClient("id", "http://localhost:8501/").exchange_code("c", "v")

    (request,) = made
    assert str(request.url) == cyclemate.TOKEN_URL
    assert "Authorization" not in request.headers
    assert form(request) == {
        "grant_type": "authorization_code",
        "code": "c",
        "redirect_uri": "http://localhost:8501/",
        "code_verifier": "v",
        "client_id": "id",
    }
    assert token["access_token"] == "access-1"
    assert not token.is_expired()


def test_confidential_client_uses_basic_auth(requests):
    made, responses = requests
    responses["/auth/v1/oauth/token"] = httpx.Response(200, json=TOKEN)
    OAuthClient("id", "http://localhost:8501/", "secret").exchange_code("c", "v")

    (request,) = made
    assert (
        request.headers["Authorization"] == httpx.BasicAuth("id", "secret")._auth_header
    )
    assert "client_id" not in form(request)


def test_refresh_rotates_the_refresh_token(requests):
    made, responses = requests
    client = OAuthClient("id", "http://localhost:8501/")
    responses["/auth/v1/oauth/token"] = httpx.Response(
        200, json={**TOKEN, "access_token": "access-2", "refresh_token": "refresh-2"}
    )
    token = client.refresh(cyclemate.OAuth2Token.from_dict(TOKEN))
    assert form(made[0]) == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
        "client_id": "id",
    }
    assert (token["access_token"], token["refresh_token"]) == ("access-2", "refresh-2")

    # keeps the old one when there's no new one
    responses["/auth/v1/oauth/token"] = httpx.Response(
        200, json={"access_token": "access-3", "expires_in": 3600}
    )
    assert client.refresh(token)["refresh_token"] == "refresh-2"


def test_token_errors_say_why(requests):
    _, responses = requests
    responses["/auth/v1/oauth/token"] = httpx.Response(
        400, json={"error": "invalid_grant", "error_description": "code expired"}
    )
    with pytest.raises(cyclemate.OAuthError, match="code expired"):
        OAuthClient("id", "http://localhost:8501/").exchange_code("c", "v")
