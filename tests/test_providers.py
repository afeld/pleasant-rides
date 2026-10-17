import asyncio
import json

import httpx
import pytest

from pleasant_rides.models import Point
from pleasant_rides.politeness import ProviderError, is_rate_limited, is_retryable
from pleasant_rides.providers import iter_routes, redact
from pleasant_rides.providers.base import MissingAPIKey, Provider
from pleasant_rides.providers.brouter import BRouter
from pleasant_rides.providers.valhalla import PLEASANT_OPTIONS, Valhalla

ORIGIN = Point(40.0, -74.0)
DESTINATION = Point(40.01, -74.0)

GEOJSON = {
    "features": [{"geometry": {"coordinates": [[-74.0, 40.0, 10], [-74.0, 40.01, 12]]}}]
}


class Fake(Provider):
    name = "Fake"
    api_key_var = "FAKE_API_KEY"

    def __init__(self, labels=("Route",)):
        self.labels = labels

    async def fetch(self, origin, destination):
        return [(label, [origin, destination]) for label in self.labels]


@pytest.fixture
def requests(monkeypatch):
    """Answers the providers' HTTP requests with GEOJSON, returning the list of requests made."""
    made: list[httpx.Request] = []

    def handle(request: httpx.Request):
        made.append(request)
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"profileid": "custom_123"})
        return httpx.Response(200, json=GEOJSON)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs),
    )
    return made


def test_repeated_labels_are_numbered():
    routes = asyncio.run(
        Fake(["Route", "Route", "Other"]).get_routes(ORIGIN, DESTINATION)
    )
    assert [r.label for r in routes] == ["Route", "Route (2)", "Other"]


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("FAKE_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey, match="FAKE_API_KEY"):
        _ = Fake().api_key


def test_cache_key_depends_on_settings():
    assert Valhalla().cache_key == Valhalla(dict(PLEASANT_OPTIONS)).cache_key
    assert (
        Valhalla().cache_key
        != Valhalla({**PLEASANT_OPTIONS, "use_hills": 0.1}).cache_key
    )
    assert BRouter("trekking").cache_key != BRouter("safety").cache_key


def test_brouter_cache_key_depends_on_profile_contents(tmp_path):
    profile = tmp_path / "test.brf"
    profile.write_text("one")
    before = BRouter(profile).cache_key
    profile.write_text("two")
    assert BRouter(profile).cache_key != before


def test_brouter_uploads_local_profiles(requests, tmp_path):
    profile = tmp_path / "test.brf"
    profile.write_text("---context:global")
    routes = asyncio.run(BRouter(profile).get_routes(ORIGIN, DESTINATION))

    upload, route = requests
    assert upload.content == b"---context:global"
    assert route.url.params["profile"] == "custom_123"
    assert routes[0].label == "BRouter (test)"
    # GeoJSON is [lon, lat(, elevation)]
    assert routes[0].points == (Point(40.0, -74.0), Point(40.01, -74.0))


def test_brouter_params(requests):
    asyncio.run(
        BRouter("trekking", {"consider_traffic": 0.5, "allow_steps": False}).get_routes(
            ORIGIN, DESTINATION
        )
    )
    (route,) = requests
    assert route.url.params["profile"] == "trekking"
    assert route.url.params["profile:consider_traffic"] == "0.5"
    # the server rejects "true"/"false"
    assert route.url.params["profile:allow_steps"] == "0"


def test_valhalla_sends_its_costing_options(requests):
    options = {"use_hills": 0.1}
    # the fake response isn't in Valhalla's format; only the request matters here
    with pytest.raises(KeyError):
        asyncio.run(Valhalla(options).get_routes(ORIGIN, DESTINATION))
    (route,) = requests
    params = json.loads(route.url.params["json"])
    assert params["costing_options"] == {"bicycle": options}


def test_redact(monkeypatch):
    monkeypatch.setenv("SOME_API_KEY", "s3cret")
    assert redact("failed with s3cret") == "failed with <SOME_API_KEY>"
    assert redact("GET /route?key=abc&x=1") == "GET /route?key=<redacted>&x=1"


def test_iter_routes_reports_failures_per_provider(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "s3cret")

    async def fetch(provider, origin, destination):
        if provider.name == "Valhalla":
            raise RuntimeError("down, key s3cret")
        return []

    async def collect():
        return [r async for r in iter_routes(ORIGIN, DESTINATION, fetch)]

    results = {name: (routes, error) for name, routes, error in asyncio.run(collect())}
    routes, error = results["Valhalla"]
    assert routes is None
    assert error == "Valhalla: skipped (RuntimeError: down, key <GOOGLE_MAPS_API_KEY>)"
    assert results["BRouter"] == ([], None)


@pytest.mark.parametrize(
    "status, text, retryable, rate_limited",
    [
        (
            400,
            "operation killed by thread-priority-watchdog after 2 seconds",
            True,
            False,
        ),
        (403, "Please, retry later!", False, True),
        (400, "some other problem", False, False),
        (500, "", True, False),
    ],
)
def test_brouter_errors(monkeypatch, status, text, retryable, rate_limited):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, text=text)
            ),
            **kwargs,
        ),
    )
    with pytest.raises(ProviderError) as error:
        asyncio.run(BRouter("trekking").get_routes(ORIGIN, DESTINATION))
    assert is_retryable(error.value) == retryable
    assert is_rate_limited(error.value) == rate_limited
