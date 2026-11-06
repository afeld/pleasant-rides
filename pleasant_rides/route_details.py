"""What the route page says about a single route, worked out from its road segments (edges)."""

from collections import defaultdict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from itertools import groupby
from math import ceil

from .edges import (
    CAR_FREE_USES,
    bike_lane_kind,
    describe,
    posted,
    road_kind,
    surface_kind,
    total_km,
)
from .map import Segment
from .map_matching import Edge
from .metrics import Metric
from .scoring import Scorecard, edge_scores
from .units import KM_PER_MILE, METERS_PER_FOOT


def route_segments(edges: list[Edge]):
    """The route's road segments, for coloring it on the map."""
    return [
        Segment(e["length"], score, describe(e))
        for e, score in zip(edges, edge_scores(edges))
    ]


@dataclass(frozen=True)
class Stretch:
    """Consecutive road segments that are alike, since a route's hundreds of segments would be too many to read."""

    start_mi: float
    miles: float
    description: str
    # 0-100, the length-weighted average of its segments' scores
    score: float | None
    # percent, or None if not known
    steepest_grade: float | None
    speed_limit_mph: int | None


def _speed_limit_mph(edge: Edge):
    # Valhalla gives speed limits in km/h
    return round(edge["speed_limit"] / KM_PER_MILE) if posted([edge]) else None


def _alike(edge: Edge):
    return describe(edge), _speed_limit_mph(edge)


def _weighted_score(edges: list[Edge]):
    scored = [
        (score, e["length"])
        for e, score in zip(edges, edge_scores(edges))
        if score is not None
    ]
    km = sum(length for _, length in scored)
    return sum(score * length for score, length in scored) / km if km else None


def stretches(edges: list[Edge]):
    """The route from start to end, with consecutive road segments that are alike merged."""
    result: list[Stretch] = []
    start_mi = 0.0
    for (description, speed_limit_mph), group in groupby(edges, _alike):
        segments = list(group)
        miles = total_km(segments) / KM_PER_MILE
        grades = [e["max_upward_grade"] for e in segments if "max_upward_grade" in e]
        result.append(
            Stretch(
                start_mi,
                miles,
                description,
                _weighted_score(segments),
                max(grades, default=None),
                speed_limit_mph,
            )
        )
        start_mi += miles
    return result


def mix(edges: list[Edge], kind: Callable[[Edge], Hashable]):
    """[(kind, miles), ...] of the route, most miles first."""
    miles: defaultdict[Hashable, float] = defaultdict(float)
    for edge in edges:
        miles[kind(edge)] += edge["length"] / KM_PER_MILE
    return sorted(miles.items(), key=lambda pair: pair[1], reverse=True)


def _bike_facility(edge: Edge):
    if edge.get("use") in CAR_FREE_USES:
        return "car-free"
    return bike_lane_kind(edge) or "no bike lane"


# what each of the route's mixes is of
MIXES: dict[str, Callable[[Edge], str]] = {
    "Road type": road_kind,
    "Bike facilities": _bike_facility,
    "Surface": lambda edge: surface_kind(edge) or "unknown",
}


def elevation_profile(edges: list[Edge], max_points: int = 500):
    """[{"mile", "elevation_ft"}, ...] at the middle of each road segment with a known elevation, thinned out to at most `max_points` to keep the page small on long routes."""
    profile = []
    start_mi = 0.0
    for edge in edges:
        miles = edge["length"] / KM_PER_MILE
        if edge.get("mean_elevation") is not None:
            profile.append(
                {
                    "mile": start_mi + miles / 2,
                    "elevation_ft": edge["mean_elevation"] / METERS_PER_FOOT,
                }
            )
        start_mi += miles
    return profile[:: ceil(len(profile) / max_points) or 1]


def format_value(metric: Metric, value: float | None):
    """`value` the way the app displays `metric`."""
    if value is None:
        return "n/a"
    return f"{value:.0%}" if metric.format == "percent" else metric.format % value


def credit(card: Scorecard, metric: Metric):
    """How much of the credit (0-1) the route gets for `metric`, or None if `metric` doesn't count toward its score."""
    value = card.values.get(metric.key)
    return metric.score(value) if metric.weight and value is not None else None
