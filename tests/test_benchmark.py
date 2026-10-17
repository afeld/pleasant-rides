import asyncio

import pytest

from pleasant_rides import benchmark
from pleasant_rides.benchmark import (
    TRIPS,
    VARIANTS,
    TripResult,
    TripScore,
    run_variants,
    table_row,
)
from pleasant_rides.models import Point, Route
from pleasant_rides.politeness import ProviderError
from pleasant_rides.providers.base import MissingAPIKey

BIKE_PATH = {"length": 1.0, "use": "cycleway", "road_class": "service_other"}
VALHALLA = "Valhalla (current)"
BROUTER = "BRouter (current)"


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(benchmark, "RETRY_AFTER_S", 0)


def route(provider, origin, destination):
    return Route(provider.name, "Route", (origin, destination))


async def fetch(provider, origin, destination):
    return [route(provider, origin, destination)], 1.5


async def get_edges(points):
    return [BIKE_PATH]


async def no_surroundings(routes):
    raise RuntimeError("Overture is down")


def run(names, fetch=fetch, get_edges=get_edges, get_surroundings=no_surroundings):
    steps = []
    results = asyncio.run(
        run_variants(names, fetch, get_edges, get_surroundings, steps.append)
    )
    return results, steps


def test_scores_each_variant_on_each_trip():
    results, steps = run([VALHALLA, BROUTER])
    for name in [VALHALLA, BROUTER]:
        assert set(results.trips[name]) == set(TRIPS)
        for result in results.trips[name].values():
            assert isinstance(result, TripScore)
            assert result.score == pytest.approx(100)
            assert (result.km, result.seconds) == (1.0, 1.5)
    assert len(steps) == benchmark.steps([VALHALLA, BROUTER])


def test_records_surroundings_errors_per_trip():
    results, _ = run([VALHALLA])
    assert results.surroundings_errors == {
        trip: "RuntimeError: Overture is down" for trip in TRIPS
    }


def test_fetches_surroundings_once_per_trip_for_all_its_routes():
    calls = []

    async def get_surroundings(routes):
        calls.append(routes)
        raise RuntimeError("Overture is down")

    run([VALHALLA, BROUTER], get_surroundings=get_surroundings)
    assert len(calls) == len(TRIPS)
    assert all(len(routes) == 2 for routes in calls)


def test_retries_errors_that_might_go_away():
    attempts = []

    async def flaky(provider, origin, destination):
        attempts.append(provider)
        if len(attempts) == 1:
            raise ProviderError("server busy", retryable=True)
        return await fetch(provider, origin, destination)

    results, _ = run([VALHALLA], fetch=flaky)
    assert all(isinstance(r, TripScore) for r in results.trips[VALHALLA].values())
    assert len(attempts) == len(TRIPS) + 1


def test_gives_up_after_repeated_failures():
    attempts = []

    async def busy(provider, origin, destination):
        attempts.append(provider)
        raise ProviderError("server busy", retryable=True)

    results, _ = run([VALHALLA], fetch=busy)
    assert set(results.trips[VALHALLA].values()) == {"ProviderError: server busy"}
    assert len(attempts) == len(TRIPS) * benchmark.ATTEMPTS


def test_doesnt_retry_errors_that_wont_go_away():
    attempts = []

    async def bad_request(provider, origin, destination):
        attempts.append(provider)
        raise ProviderError("GraphHopper 400: Free packages cannot use flexible mode")

    run([VALHALLA], fetch=bad_request)
    assert len(attempts) == len(TRIPS)


def test_stops_requests_to_a_server_that_rate_limits():
    attempts = []

    async def rate_limited(provider, origin, destination):
        attempts.append(provider.name)
        if provider.name == "BRouter":
            raise ProviderError("BRouter 403: Please, retry later!", rate_limited=True)
        return await fetch(provider, origin, destination)

    stronger = "BRouter: pleasant, stronger penalties"
    results, _ = run([BROUTER, stronger, VALHALLA], fetch=rate_limited)
    # one request to BRouter, then none
    assert attempts.count("BRouter") == 1
    first, *rest = results.trips[BROUTER].values()
    assert first == "ProviderError: BRouter 403: Please, retry later!"
    for result in [*rest, *results.trips[stronger].values()]:
        assert isinstance(result, str) and result.startswith(
            "skipped, since BRouter asked for fewer requests"
        )
    # other providers are unaffected
    assert all(isinstance(r, TripScore) for r in results.trips[VALHALLA].values())


def test_map_matching_shares_valhallas_backoff():
    async def rate_limited(points):
        raise ProviderError("Valhalla 429: slow down", rate_limited=True)

    calls = []

    async def counting(points):
        calls.append(points)
        return await rate_limited(points)

    results, _ = run([VALHALLA, BROUTER], get_edges=counting)
    assert len(calls) == 1
    assert all(isinstance(r, str) for r in results.trips[BROUTER].values())


def test_doesnt_retry_missing_api_keys():
    attempts = []

    async def no_key(provider, origin, destination):
        attempts.append(provider)
        raise MissingAPIKey("set SOME_API_KEY")

    results, _ = run([VALHALLA], fetch=no_key)
    assert set(results.trips[VALHALLA].values()) == {"skipped (set SOME_API_KEY)"}
    assert len(attempts) == len(TRIPS)


def test_map_matching_failures_are_per_route():
    async def picky(points):
        if points[0] == next(iter(TRIPS.values()))[0]:
            raise RuntimeError("no match")
        return [BIKE_PATH]

    results, _ = run([VALHALLA], get_edges=picky)
    first, *rest = results.trips[VALHALLA].values()
    assert first == "RuntimeError: no match"
    assert all(isinstance(r, TripScore) for r in rest)


def test_table_row():
    trips = {
        trip: TripScore(score, km, seconds)
        for trip, score, km, seconds in zip(
            TRIPS, [80, 90, 60, 70], [100, 10, 5, 30], [2, 1, 0.5, 1.5]
        )
    }
    row = table_row(VALHALLA, trips)
    assert row["Provider"] == "Valhalla"
    assert row["Mean"] == 75
    assert row["Routing s"] == 5
    assert row["Long score"] == 80
    assert row["Long km"] == 100
    assert row["Long s"] == 2


def test_table_row_leaves_out_totals_when_a_trip_failed():
    trips: dict[str, TripResult] = {trip: TripScore(80, 10, 1) for trip in TRIPS}
    trips[next(iter(TRIPS))] = "RuntimeError: down"
    row = table_row(VALHALLA, trips)
    assert row["Mean"] is None
    assert row["Routing s"] is None
    assert row["Long score"] is None


def test_variants_have_unique_cache_keys():
    keys = [provider.cache_key for provider in VARIANTS.values()]
    assert len(keys) == len(set(keys))


def test_trip_endpoints_are_points():
    for origin, destination in TRIPS.values():
        assert isinstance(origin, Point) and isinstance(destination, Point)
