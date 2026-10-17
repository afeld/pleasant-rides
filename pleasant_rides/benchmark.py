"""Provider variants (e.g. different routing parameters) and sample trips to compare them on, for the app's Benchmark
page. Add a variant to VARIANTS to try it.

Results depend on the providers' live servers and map data, so they can drift over time; compare new variants against
the baselines (the "(current)" ones) from the same run.
"""

import asyncio
import statistics
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

from . import map_matching, scoring, surroundings
from .map_matching import Edge
from .metrics import Ride
from .models import Point, Route
from .politeness import is_rate_limited, is_retryable
from .providers import PROVIDERS, fetch_routes_timed, valhalla
from .providers.base import MissingAPIKey, Provider
from .providers.brouter import BRouter
from .providers.graphhopper import GraphHopper
from .providers.valhalla import PLEASANT_OPTIONS, Valhalla
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

# for errors that might go away, like a busy server; see politeness.is_retryable()
ATTEMPTS = 3
RETRY_AFTER_S = 10

# returns the routes and how many seconds the provider took
Fetch = Callable[[Provider, Point, Point], Awaitable[tuple[list[Route], float]]]
GetEdges = Callable[[Sequence[Point]], Awaitable[list[Edge]]]
GetSurroundings = Callable[[tuple[Sequence[Point], ...]], Awaitable[Surroundings]]


@dataclass(frozen=True)
class TripScore:
    score: float
    km: float
    # how long the provider took to return the routes when they were fetched, even if they now come from a cache
    seconds: float


# a TripScore, or an error message
TripResult = TripScore | str

T = TypeVar("T")


class _Backoffs:
    """Which servers have asked for fewer requests during a run, so they don't get any more."""

    def __init__(self):
        # server -> why it's skipped
        self.reasons: dict[str, str] = {}

    async def attempt(self, server: str, call: Callable[[], Awaitable[T]]) -> T | str:
        """Returns what `call()` does, or an error message.

        Only retries errors that might go away (like a busy server), and not at all once `server` has rate-limited us.
        """
        if server in self.reasons:
            return self.reasons[server]
        error = ""
        for attempt in range(ATTEMPTS):
            if attempt:
                await asyncio.sleep(RETRY_AFTER_S)
            try:
                return await call()
            except MissingAPIKey as e:
                return f"skipped ({e})"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                if is_rate_limited(e):
                    self.reasons[server] = (
                        f"skipped, since {server} asked for fewer requests ({error})"
                    )
                    return error
                if not is_retryable(e):
                    return error
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
    fetch: Fetch = fetch_routes_timed,
    get_edges: GetEdges = map_matching.get_edges,
    get_surroundings: GetSurroundings = surroundings.get_surroundings,
    on_step: Callable[[str], None] = lambda message: None,
):
    """Scores each variant's first route on each trip.

    First fetches the routes: each provider's variants one at a time, to be polite to its server, but different
    providers concurrently. Then, for each trip, fetches the surroundings of all of its routes at once (as the planner
    does, since they mostly overlap), map-matches the routes one at a time, and scores them. Once a server rate-limits
    the run, it gets no more requests. The API calls default to calling the APIs directly; pass cached versions to
    reuse results. `on_step(message)` is called after each variant's routes and each trip's scores.
    """
    backoffs = _Backoffs()
    by_provider: dict[str, list[str]] = defaultdict(list)
    for name in names:
        by_provider[VARIANTS[name].name].append(name)
    # variant name -> trip -> (the first route's points, seconds), or an error message
    points: dict[str, dict[str, tuple[Sequence[Point], float] | str]] = {}

    async def fetch_first(provider: Provider, origin: Point, destination: Point):
        routes, seconds = await fetch(provider, origin, destination)
        return routes[0].points, seconds

    async def fetch_provider(variant_names: list[str]):
        for name in variant_names:
            provider = VARIANTS[name]
            server = provider.server or provider.name
            points[name] = {
                trip: await backoffs.attempt(
                    server,
                    lambda provider=provider, ends=ends: fetch_first(provider, *ends),
                )
                for trip, ends in TRIPS.items()
            }
            on_step(f"Fetched routes: {name}")

    await asyncio.gather(*(fetch_provider(v) for v in by_provider.values()))

    results = Results({name: {} for name in names}, {})
    for trip in TRIPS:
        routes = {
            name: fetched[0]
            for name in names
            if not isinstance(fetched := points[name][trip], str)
        }
        found = await backoffs.attempt(
            "Overture Maps",
            lambda routes=routes: get_surroundings(tuple(routes.values())),
        )
        if isinstance(found, str):
            results.surroundings_errors[trip] = found
        around = None if isinstance(found, str) else found
        edges = {
            name: await backoffs.attempt(
                valhalla.SERVER, lambda route=route: get_edges(route)
            )
            for name, route in routes.items()
        }
        for name in names:
            fetched, route_edges = points[name][trip], edges.get(name, "")
            if isinstance(fetched, str):
                results.trips[name][trip] = fetched
            elif isinstance(route_edges, str):
                results.trips[name][trip] = route_edges
            else:
                route, seconds = fetched
                card = scoring.score(Ride(route, route_edges, around))
                results.trips[name][trip] = TripScore(
                    card.total, card.values["distance_km"], seconds
                )
        on_step(f"Scored: {trip}")

    return results


def short(trip: str):
    """e.g. "Long" from "Long: Brooklyn→Beacon"."""
    return trip.split(":")[0]


def table_row(name: str, trips: Mapping[str, TripResult]):
    """A variant's row in the results table.

    The mean score and total routing time are only filled in when every trip worked, since they're only comparable then.
    """
    scored = [r for r in trips.values() if isinstance(r, TripScore)]
    complete = len(scored) == len(TRIPS)
    cells = {}
    for trip, result in trips.items():
        ok = isinstance(result, TripScore)
        cells[f"{short(trip)} score"] = result.score if ok else None
        cells[f"{short(trip)} km"] = result.km if ok else None
        cells[f"{short(trip)} s"] = result.seconds if ok else None
    return {
        "Variant": name,
        "Provider": VARIANTS[name].name,
        "Mean": statistics.mean(r.score for r in scored) if complete else None,
        "Routing s": sum(r.seconds for r in scored) if complete else None,
        **cells,
    }
