"""Scores routes against the README's working definition of "pleasant", using road attributes from OpenStreetMap.

Each route is map-matched with Valhalla's `trace_attributes`, which returns the edges (road segments) it follows and
the intersections between them. Most metrics are the share of the route's distance that meets a condition; turns and
intersections are counted per km. Not covered yet: scenery, points of interest, and remoteness.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from .models import Point

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
class Metric:
    key: str
    label: str
    help: str = ""
    # how much it counts toward the overall score; 0 for metrics that are only shown
    weight: float = 0
    # how the app displays it: "percent", or a printf-style format
    format: str = "%.0f"

    def measure(self, edges: list[Edge]):
        """The value shown for a map-matched route, or None if it doesn't apply."""
        raise NotImplementedError

    def score(self, value: float):
        """`value` as 0-1, higher being better."""
        return value


# keyword-only, so these fields can be required even though Metric's later ones have defaults
@dataclass(frozen=True, kw_only=True)
class Total(Metric):
    """A number for the whole route, such as its distance."""

    compute: Callable[[list[Edge]], float]

    def measure(self, edges: list[Edge]):
        return self.compute(edges)


@dataclass(frozen=True, kw_only=True)
class Share(Metric):
    """The share (0-1) of the route's distance that meets `condition`, out of the edges that `of` selects."""

    condition: Callable[[Edge], bool]
    of: Callable[[list[Edge]], list[Edge]] = lambda edges: edges
    format: str = field(default="percent", init=False)

    def measure(self, edges: list[Edge]):
        edges = self.of(edges)
        total = _km(edges)
        return _km([e for e in edges if self.condition(e)]) / total if total else None


@dataclass(frozen=True, kw_only=True)
class PerKm(Metric):
    """How many times something happens per km, where fewer is better."""

    count: Callable[[list[Edge]], int]
    # the rate that scores 0.5
    half_score: float = 1
    format: str = "%.1f"

    def measure(self, edges: list[Edge]):
        km = _km(edges)
        return self.count(edges) / km if km else None

    def score(self, value: float):
        return self.half_score / (self.half_score + value)


# in the order they're shown, grouped as in the README
METRICS = [
    Total("distance_km", "Distance (km)", compute=_km),
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


def score(edges: list[Edge]):
    values = {m.key: m.measure(edges) for m in METRICS}
    weighted = [
        (m.score(values[m.key]), m.weight)
        for m in METRICS
        if m.weight and values[m.key] is not None
    ]
    total = 100 * sum(s * w for s, w in weighted) / sum(w for _, w in weighted)
    return Scorecard(values, total)


async def score_route(points: Sequence[Point]):
    return score(await get_edges(points))
