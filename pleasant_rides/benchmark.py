"""Provider variants (e.g. different routing parameters) and sample trips to compare them on, for the app's Benchmark
page. Add a variant to VARIANTS to try it.

Results depend on the providers' live servers and map data, so they can drift over time; compare new variants against
the baselines (the "(current)" ones) from the same run.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from . import scoring, surroundings
from .models import Point, Route
from .providers import PROVIDERS, fetch_routes
from .providers.base import MissingAPIKey, Provider
from .providers.brouter import BRouter
from .providers.graphhopper import GraphHopper
from .providers.valhalla import PLEASANT_OPTIONS, Valhalla
from .scoring import Edge, Ride
from .surroundings import Surroundings

TRIPS = {
    "Long: Brooklyn→Beacon": (Point(40.6782, -73.9442), Point(41.5048, -73.9696)),
    "Urban: Park Slope→UWS": (Point(40.6710, -73.9814), Point(40.7870, -73.9754)),
    "Rural: Beacon→Cold Spring": (
        Point(41.5048, -73.9696),
        Point(41.4201, -73.9546),
    ),
    "Suburban: Hoboken→Montclair": (
        Point(40.7440, -74.0324),
        Point(40.8259, -74.2090),
    ),
}

# the stronger penalties tried on BRouter's pleasant.brf
STRONGER_BROUTER = {
    "fast_penalty": 2,
    "lanes_penalty": 1,
    "uphillcost": 100,
    "primary_cost": 3,
    "secondary_cost": 2,
    "tertiary_cost": 1.3,
    "consider_traffic": 1.5,
}

# by name; the providers as the app uses them come first, as the baselines
VARIANTS: dict[str, Provider] = {
    **{f"{name} (current)": provider for name, provider in PROVIDERS.items()},
    "Valhalla: previous (road bike, use_roads 0.2)": Valhalla(
        {
            "bicycle_type": "road",
            "use_roads": 0.2,
            "use_hills": 0.3,
            "use_ferry": 0.0,
            "avoid_bad_surfaces": 0.8,
        }
    ),
    "Valhalla: + turn penalty, living streets": Valhalla(
        {**PLEASANT_OPTIONS, "maneuver_penalty": 30, "use_living_streets": 1.0}
    ),
    "Valhalla: avoid ferries": Valhalla({**PLEASANT_OPTIONS, "use_ferry": 0.0}),
    "Valhalla: use_hills 0.1": Valhalla({**PLEASANT_OPTIONS, "use_hills": 0.1}),
    "BRouter: pleasant, stronger penalties": BRouter(params=STRONGER_BROUTER),
    "BRouter: pleasant + forests/rivers": BRouter(
        params={"consider_forest": True, "consider_river": True}
    ),
    **{
        f"BRouter: {profile}": BRouter(profile)
        for profile in [
            "fastbike-lowtraffic",
            "fastbike-verylowtraffic",
            "racebike-verylowtraffic",
            "safety",
            "trekking",
        ]
    },
    "BRouter: quaelnix-gravel, traffic/cycle routes/inclines": BRouter(
        "quaelnix-gravel",
        {
            "consider_traffic_estimate": True,
            "prefer_cycle_routes": True,
            "avoid_steep_inclines": True,
        },
    ),
    # other cycling profiles and custom models need a paid plan
    "GraphHopper: custom model": GraphHopper(custom_model=True),
}

ATTEMPTS = 3
RETRY_AFTER_S = 5
# map matching goes through Valhalla's public server, so go easy on it
MAP_MATCHING_CONCURRENCY = 2

Fetch = Callable[[Provider, Point, Point], Awaitable[list[Route]]]
GetEdges = Callable[[Sequence[Point]], Awaitable[list[Edge]]]
GetSurroundings = Callable[[tuple[Sequence[Point], ...]], Awaitable[Surroundings]]
# (score, km) for a trip, or an error message
TripResult = tuple[float, float] | str

T = TypeVar("T")


async def _attempt(call: Callable[[], Awaitable[T]]) -> T | str:
    """Returns what `call()` does, or an error message if it keeps failing."""
    error = ""
    for attempt in range(ATTEMPTS):
        if attempt:
            await asyncio.sleep(RETRY_AFTER_S)
        try:
            return await call()
        except MissingAPIKey as e:
            return f"skipped ({e})"
        except Exception as e:
            # the public servers fail on long routes now and then, which tends to work on a retry
            error = f"{type(e).__name__}: {e}"
    return error


@dataclass
class Results:
    # variant name -> trip -> TripResult
    trips: dict[str, dict[str, TripResult]]
    # trip -> why its routes' surroundings couldn't be fetched, which leaves scenery, points of interest, and
    # remoteness unscored for that trip
    surroundings_errors: dict[str, str]


def steps(names: list[str]):
    """How many times `run_variants()` calls `on_step()`."""
    return len(names) + len(TRIPS)


async def run_variants(
    names: list[str],
    fetch: Fetch = fetch_routes,
    get_edges: GetEdges = scoring.get_edges,
    get_surroundings: GetSurroundings = surroundings.get_surroundings,
    on_step: Callable[[str], None] = lambda message: None,
):
    """Scores each variant's first route on each trip.

    First fetches the routes: each provider's variants one at a time, to not overload its server, but different
    providers concurrently. Then, for each trip, fetches the surroundings of all of its routes at once (as the planner
    does, since they mostly overlap) and scores them. The API calls default to calling the APIs directly; pass cached
    versions to reuse results. `on_step(message)` is called after each variant's routes and each trip's scores.
    """
    by_provider: dict[str, list[str]] = defaultdict(list)
    for name in names:
        by_provider[VARIANTS[name].name].append(name)
    # variant name -> trip -> the first route's points, or an error message
    points: dict[str, dict[str, Sequence[Point] | str]] = {}

    async def fetch_first(provider: Provider, origin: Point, destination: Point):
        return (await fetch(provider, origin, destination))[0].points

    async def fetch_provider(variant_names: list[str]):
        for name in variant_names:
            points[name] = {
                trip: await _attempt(lambda: fetch_first(VARIANTS[name], *ends))
                for trip, ends in TRIPS.items()
            }
            on_step(f"Fetched routes: {name}")

    await asyncio.gather(*(fetch_provider(v) for v in by_provider.values()))

    results = Results({name: {} for name in names}, {})
    map_matching = asyncio.Semaphore(MAP_MATCHING_CONCURRENCY)

    async def edges_for(route: Sequence[Point]):
        async with map_matching:
            return await _attempt(lambda: get_edges(route))

    for trip in TRIPS:
        routes = {
            name: route
            for name in names
            if not isinstance(route := points[name][trip], str)
        }
        found = await _attempt(lambda: get_surroundings(tuple(routes.values())))
        if isinstance(found, str):
            results.surroundings_errors[trip] = found
        around = None if isinstance(found, str) else found
        edges = dict(
            zip(routes, await asyncio.gather(*map(edges_for, routes.values())))
        )
        for name in names:
            route, route_edges = points[name][trip], edges.get(name, "")
            if isinstance(route, str):
                results.trips[name][trip] = route
            elif isinstance(route_edges, str):
                results.trips[name][trip] = route_edges
            else:
                card = scoring.score(Ride(route, route_edges, around))
                results.trips[name][trip] = card.total, card.values["distance_km"]
        on_step(f"Scored: {trip}")

    return results
