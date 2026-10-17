"""Scores routes against the README's working definition of "pleasant".

Road attributes come from OpenStreetMap: each route is map-matched with Valhalla's `trace_attributes`, which returns the edges (road segments) it follows and the intersections between them. Scenery, points of interest, and remoteness come from Overture Maps (see `surroundings`). Most metrics are the share of the route's distance that meets a condition; turns, intersections, and sights are counted per km.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import surroundings
from .models import Point
from .surroundings import Surroundings

# a road segment from Valhalla's trace_attributes
Edge = dict[str, Any]

URL = "https://valhalla1.openstreetmap.de/trace_attributes"

ATTRIBUTES = [
    "edge.length",
    "edge.road_class",
    "edge.use",
    "edge.cycle_lane",
    "edge.bicycle_network",
    "edge.speed_limit",
    "edge.lane_count",
    "edge.surface",
    "edge.sac_scale",
    "edge.mean_elevation",
    "edge.max_upward_grade",
    "edge.begin_heading",
    "edge.end_heading",
    "edge.internal_intersection",
    "edge.roundabout",
    "edge.forward",
    "edge.traversability",
    "node.intersecting_edge.use",
    "node.intersecting_edge.driveability",
]

# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
BUSY_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary"}
CAR_FREE_USES = {
    "cycleway",
    "path",
    "footway",
    "pedestrian",
    "mountain_bike",
    "living_street",
    "track",
    "steps",
}
SEPARATED_CYCLE_LANES = {"dedicated", "separated"}
# pavement, boardwalks, and crushed gravel (OSM's "compacted"/"fine_gravel") are all fine
ROUGH_SURFACES = {"dirt", "gravel", "path", "impassable"}
# where you'd usually have to get off and walk
WALKING_USES = {"steps", "footway", "pedestrian", "sidewalk"}

FAST_KPH = 50  # ~30 mph
STEEP_GRADE = 6  # percent
TURN_DEGREES = 45  # a smaller change in heading between road segments is just a bend


async def get_edges(points: Sequence[Point]):
    """Map-matches `points` [(lat, lon), ...] to the road network, returning Valhalla's edges."""
    body = {
        "shape": [{"lat": lat, "lon": lon} for lat, lon in points],
        "costing": "bicycle",
        "shape_match": "map_snap",
        "filters": {"attributes": ATTRIBUTES, "action": "include"},
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(URL, json=body, timeout=120.0)
    if response.is_error:
        raise RuntimeError(
            f"Valhalla {response.status_code}: {response.json().get('error')}"
        )
    return response.json()["edges"]


def _is_low_traffic(edge: Edge):
    return (
        edge.get("use") in CAR_FREE_USES
        or edge.get("cycle_lane") in SEPARATED_CYCLE_LANES
        or edge.get("road_class") not in BUSY_ROAD_CLASSES
    )


def _is_walking(edge: Edge):
    # riding against the edge's allowed direction means it's a one-way the wrong way
    wrong_way = edge.get("traversability") == (
        "backward" if edge.get("forward", True) else "forward"
    )
    return edge.get("use") in WALKING_USES or edge.get("sac_scale", 0) > 0 or wrong_way


def _turns(edges: list[Edge]):
    """Changes in heading of more than TURN_DEGREES between consecutive road segments."""
    # segments inside an intersection (e.g. between a divided road's two sides) and roundabouts aren't turns of their
    # own, and would double count the turn they're part of
    segments = [
        e
        for e in edges
        if not e.get("internal_intersection") and not e.get("roundabout")
    ]
    turns = 0
    for a, b in zip(segments, segments[1:]):
        if "end_heading" not in a or "begin_heading" not in b:
            continue
        change = abs((b["begin_heading"] - a["end_heading"] + 180) % 360 - 180)
        turns += change > TURN_DEGREES
    return turns


def _intersections(edges: list[Edge]):
    """Nodes along the route where it crosses or meets a road that cars can use, other than service roads/driveways."""
    return sum(
        any(
            i.get("use") == "road" and i.get("driveability", "none") != "none"
            for i in e.get("end_node", {}).get("intersecting_edges", [])
        )
        for e in edges[:-1]
    )


def _climb(edges: list[Edge]):
    """Total elevation gain in meters, from the change in mean elevation between consecutive edges."""
    elevations = [
        e["mean_elevation"] for e in edges if e.get("mean_elevation") is not None
    ]
    return sum(max(b - a, 0) for a, b in zip(elevations, elevations[1:]))


def _roads(edges: list[Edge]):
    """Only roads have speed limits and lanes."""
    return [e for e in edges if e.get("use") not in CAR_FREE_USES]


def _posted(edges: list[Edge]):
    """Roads with a known speed limit; unknown limits are left out rather than guessed."""
    return [e for e in _roads(edges) if e.get("speed_limit")]


def _km(edges: list[Edge]):
    return sum(e["length"] for e in edges)


@dataclass(frozen=True)
class Ride:
    """Everything the metrics measure about a route."""

    points: Sequence[Point]
    edges: list[Edge]
    # None if they couldn't be fetched, in which case the metrics that use them are left out
    surroundings: Surroundings | None


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    help: str = ""
    # how much it counts toward the overall score; 0 for metrics that are only shown
    weight: float = 0
    # how the app displays it: "percent", or a printf-style format
    format: str = "%.0f"

    def measure(self, ride: Ride) -> float | None:
        """The value shown for a route, or None if it doesn't apply."""
        raise NotImplementedError

    def score(self, value: float):
        """`value` as 0-1, higher being better."""
        return value


# keyword-only, so these fields can be required even though Metric's later ones have defaults
@dataclass(frozen=True, kw_only=True)
class Total(Metric):
    """A number for the whole route, such as its distance."""

    compute: Callable[[list[Edge]], float]

    def measure(self, ride: Ride):
        return self.compute(ride.edges)


@dataclass(frozen=True, kw_only=True)
class Share(Metric):
    """The share (0-1) of the route's distance that meets `condition`, out of the edges that `of` selects."""

    condition: Callable[[Edge], bool]
    of: Callable[[list[Edge]], list[Edge]] = lambda edges: edges
    format: str = field(default="percent", init=False)

    def measure(self, ride: Ride):
        edges = self.of(ride.edges)
        total = _km(edges)
        return _km([e for e in edges if self.condition(e)]) / total if total else None


@dataclass(frozen=True, kw_only=True)
class PerKm(Metric):
    """How many times something happens per km, where fewer is better."""

    count: Callable[[list[Edge]], int]
    # the rate that scores 0.5
    half_score: float = 1
    format: str = "%.1f"

    def measure(self, ride: Ride):
        km = _km(ride.edges)
        return self.count(ride.edges) / km if km else None

    def score(self, value: float):
        return self.half_score / (self.half_score + value)


@dataclass(frozen=True, kw_only=True)
class Near(Metric):
    """The share (0-1) of the route's distance within `distance` meters of a feature in a `layer` of its surroundings."""

    layer: str
    distance: float
    format: str = field(default="percent", init=False)

    def measure(self, ride: Ride):
        if ride.surroundings is None:
            return None
        return ride.surroundings.share_near(ride.points, self.layer, self.distance)


@dataclass(frozen=True, kw_only=True)
class PassesPerKm(Metric):
    """How many features in a `layer` of the route's surroundings it passes within `distance` meters of, per km, where more is better."""

    layer: str
    distance: float
    # the rate that scores 0.5
    half_score: float = 1
    format: str = "%.1f"

    def measure(self, ride: Ride):
        km = _km(ride.edges)
        if ride.surroundings is None or not km:
            return None
        return ride.surroundings.count_near(ride.points, self.layer, self.distance) / km

    def score(self, value: float):
        return value / (self.half_score + value)


# in the order they're shown, grouped as in the README
METRICS = [
    Total("distance_km", "Distance (km)", compute=_km),
    # enjoyable
    Near(
        "green",
        "Green",
        f"Within {surroundings.GREEN_M} m of a park, woods, grass, or wetland",
        weight=2,
        layer="green",
        distance=surroundings.GREEN_M,
    ),
    Near(
        "waterside",
        "Waterside",
        f"Within {surroundings.WATER_M} m of a river, lake, or the ocean",
        weight=1,
        layer="water",
        distance=surroundings.WATER_M,
    ),
    PassesPerKm(
        "sights_per_km",
        "Sights/km",
        f"Landmarks, museums, parks, and the like within {surroundings.SIGHT_M} m",
        weight=1,
        layer="sights",
        distance=surroundings.SIGHT_M,
        half_score=0.5,
    ),
    # easy
    Share(
        "gentle",
        "Gentle",
        f"Grades under {STEEP_GRADE}%",
        weight=2,
        condition=lambda e: e.get("max_upward_grade", 0) < STEEP_GRADE,
    ),
    Total("climb_m", "Climb (m)", compute=_climb),
    PerKm(
        "turns_per_km",
        "Turns/km",
        f"Changes in direction over {TURN_DEGREES}°",
        weight=1,
        count=_turns,
        half_score=1,
    ),
    Share(
        "smooth",
        "Smooth",
        "Pavement, boardwalks, or crushed gravel",
        weight=1,
        condition=lambda e: e.get("surface") not in ROUGH_SURFACES,
    ),
    Share(
        "rideable",
        "Rideable",
        "Not stairs, footways, or the wrong way down a one-way",
        weight=2,
        condition=lambda e: not _is_walking(e),
    ),
    # safe
    Share(
        "low_traffic",
        "Low traffic",
        "Off-road, separated bike lane, or not a primary/secondary road or above",
        weight=3,
        condition=_is_low_traffic,
    ),
    PerKm(
        "intersections_per_km",
        "Intersections/km",
        "With roads open to cars, other than service roads",
        weight=1,
        count=_intersections,
        half_score=3,
    ),
    Share(
        "slow",
        "Slow",
        f"Speed limit under {FAST_KPH} km/h, of roads with a known limit",
        weight=2,
        condition=lambda e: e["speed_limit"] < FAST_KPH,
        of=_posted,
    ),
    Share(
        "few_lanes",
        "1-2 lanes",
        "Of roads",
        weight=1,
        condition=lambda e: e.get("lane_count", 1) <= 2,
        of=_roads,
    ),
    Near(
        "near_help",
        "Near help",
        f"Within {surroundings.HELP_M} m (a ~15 minute walk) of a business or other place",
        weight=1,
        layer="help",
        distance=surroundings.HELP_M,
    ),
    Share(
        "bike_network",
        "Bike network",
        "On a designated bike route",
        condition=lambda e: bool(e.get("bicycle_network")),
    ),
]


@dataclass(frozen=True)
class Scorecard:
    # metric key -> measured value (None if it doesn't apply)
    values: dict
    # 0-100, the weighted average of the metrics' scores
    total: float


def score(ride: Ride):
    values = {m.key: m.measure(ride) for m in METRICS}
    weighted = [
        (m.score(values[m.key]), m.weight)
        for m in METRICS
        if m.weight and values[m.key] is not None
    ]
    total = 100 * sum(s * w for s, w in weighted) / sum(w for _, w in weighted)
    return Scorecard(values, total)
