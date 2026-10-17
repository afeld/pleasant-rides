"""Runs the benchmark: fetches each variant's routes for the sample trips, then scores them."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass

from .. import map_matching, scoring, surroundings
from ..map_matching import Edge
from ..metrics import Ride
from ..models import Point, Route
from ..providers import fetch_routes_timed, valhalla
from ..providers.base import Provider
from ..surroundings import Surroundings
from ..trips import TRIPS
from .retries import Backoffs
from .variants import VARIANTS

# returns the routes and how many seconds the provider took
Fetch = Callable[[Provider, Point, Point], Awaitable[tuple[list[Route], float]]]
GetEdges = Callable[[Sequence[Point]], Awaitable[list[Edge]]]
GetSurroundings = Callable[[tuple[Sequence[Point], ...]], Awaitable[Surroundings]]
# a route's points and how many seconds the provider took to return it
Fetched = tuple[Sequence[Point], float]


@dataclass(frozen=True)
class TripScore:
    score: float
    km: float
    # how long the provider took to return the routes when they were fetched, even if they now come from a cache
    seconds: float


# a TripScore, or an error message
TripResult = TripScore | str


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

    First fetches all of the routes, then scores them trip by trip (see `_Run`). Once a server rate-limits the run, it
    gets no more requests. The API calls default to calling the APIs directly; pass cached versions to reuse results.
    `on_step(message)` is called after each variant's routes and each trip's scores.
    """
    run = _Run(names, fetch, get_edges, get_surroundings, on_step)
    await run.fetch_routes()
    for trip in TRIPS:
        await run.score_trip(trip)
    return run.results


class _Run:
    def __init__(
        self,
        names: list[str],
        fetch: Fetch,
        get_edges: GetEdges,
        get_surroundings: GetSurroundings,
        on_step: Callable[[str], None],
    ):
        self.names = names
        self.fetch = fetch
        self.get_edges = get_edges
        self.get_surroundings = get_surroundings
        self.on_step = on_step
        self.backoffs = Backoffs()
        # variant name -> trip -> its first route, or an error message
        self.routes: dict[str, dict[str, Fetched | str]] = {}
        self.results = Results({name: {} for name in names}, {})

    async def fetch_routes(self):
        """Each provider's variants one at a time, to be polite to its server, but different providers concurrently."""
        by_provider: dict[str, list[str]] = defaultdict(list)
        for name in self.names:
            by_provider[VARIANTS[name].name].append(name)
        await asyncio.gather(*map(self._fetch_variants, by_provider.values()))

    async def _fetch_variants(self, names: list[str]):
        for name in names:
            self.routes[name] = {
                trip: await self._fetch_first(VARIANTS[name], *ends)
                for trip, ends in TRIPS.items()
            }
            self.on_step(f"Fetched routes: {name}")

    async def _fetch_first(self, provider: Provider, origin: Point, destination: Point):
        async def fetch() -> Fetched:
            routes, seconds = await self.fetch(provider, origin, destination)
            return routes[0].points, seconds

        return await self.backoffs.attempt(provider.server or provider.name, fetch)

    async def score_trip(self, trip: str):
        """Fetches the surroundings of all of the trip's routes at once (as the planner does, since they mostly
        overlap), then map-matches the routes one at a time and scores them."""
        routes = [r[0] for r in self._trip_routes(trip) if not isinstance(r, str)]
        around = await self._surroundings(trip, routes)
        for name in self.names:
            self.results.trips[name][trip] = await self._score(
                self.routes[name][trip], around
            )
        self.on_step(f"Scored: {trip}")

    def _trip_routes(self, trip: str):
        return [self.routes[name][trip] for name in self.names]

    async def _surroundings(self, trip: str, routes: Iterable[Sequence[Point]]):
        found = await self.backoffs.attempt(
            "Overture Maps", lambda: self.get_surroundings(tuple(routes))
        )
        if isinstance(found, str):
            self.results.surroundings_errors[trip] = found
            return None
        return found

    async def _score(
        self, fetched: Fetched | str, around: Surroundings | None
    ) -> TripResult:
        if isinstance(fetched, str):
            return fetched
        route, seconds = fetched
        edges = await self.backoffs.attempt(
            valhalla.SERVER, lambda: self.get_edges(route)
        )
        if isinstance(edges, str):
            return edges
        card = scoring.score(Ride(route, edges, around))
        return TripScore(card.total, card.values["distance_km"], seconds)
