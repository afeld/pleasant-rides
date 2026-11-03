"""Scores routes against the README's working definition of "pleasant".

Road attributes come from OpenStreetMap, via map matching (see `map_matching` and `edges`). Scenery, points of interest, and remoteness come from Overture Maps (see `surroundings`). Most metrics are the share of the route's distance that meets a condition; turns, intersections, and sights are counted per mile.
"""

from dataclasses import dataclass

from . import surroundings
from .edges import (
    ROUGH_SURFACES,
    SLOW_MPH,
    STEEP_GRADE,
    TURN_DEGREES,
    climb,
    intersections,
    is_low_traffic,
    is_slow,
    is_walking,
    posted,
    roads,
    total_miles,
    turns,
)
from .map_matching import Edge
from .metrics import (
    Average,
    Away,
    Detour,
    Near,
    PassesPerMile,
    PerMile,
    Ride,
    Share,
    Total,
)
from .units import METERS_PER_FOOT, METERS_PER_MILE

# in the order they're shown, grouped as in the README
METRICS = [
    Total("distance_mi", "Distance (mi)", format="%.1f", compute=total_miles),
    # "not necessarily the most direct, but it shouldn't add a ton of time"
    Detour(
        "detour",
        "Detour (×)",
        "Distance vs. a straight line between the start and end; even direct routes on roads are typically ~1.3×",
        weight=2,
        best=1.3,
        half_score=2,
    ),
    # enjoyable
    Near(
        "green",
        "Green",
        f"Within {surroundings.GREEN_FT} ft of a park, woods, grass, or wetland",
        weight=2,
        layer="green",
        distance=surroundings.GREEN_FT * METERS_PER_FOOT,
    ),
    Near(
        "waterside",
        "Waterside",
        f"Within {surroundings.WATER_FT} ft of a river, lake, or the ocean",
        weight=1,
        layer="water",
        distance=surroundings.WATER_FT * METERS_PER_FOOT,
    ),
    PassesPerMile(
        "sights_per_mi",
        "Sights/mi",
        f"Landmarks, museums, parks, and the like within {surroundings.SIGHT_FT} ft",
        weight=1,
        layer="sights",
        distance=surroundings.SIGHT_FT * METERS_PER_FOOT,
        half_score=0.8,
    ),
    Away(
        "quiet",
        "Quiet",
        f"Not within {surroundings.QUIET_FT} ft of a motorway, trunk, or primary road",
        weight=1,
        layer="busy_roads",
        distance=surroundings.QUIET_FT * METERS_PER_FOOT,
    ),
    # easy
    Share(
        "gentle",
        "Gentle",
        f"Grades under {STEEP_GRADE}%",
        weight=2,
        condition=lambda e: e.get("max_upward_grade", 0) < STEEP_GRADE,
    ),
    Total("climb_ft", "Climb (ft)", compute=climb),
    PerMile(
        "turns_per_mi",
        "Turns/mi",
        f"Changes in direction over {TURN_DEGREES}°",
        weight=1,
        count=turns,
        half_score=1.5,
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
        condition=lambda e: not is_walking(e),
    ),
    # safe
    Share(
        "low_traffic",
        "Low traffic",
        "Off-road, separated bike lane, or not a primary/secondary road or above",
        weight=3,
        condition=is_low_traffic,
    ),
    PerMile(
        "intersections_per_mi",
        "Intersections/mi",
        "With roads open to cars, other than service roads",
        weight=1,
        count=intersections,
        half_score=5,
    ),
    Share(
        "slow",
        "Slow",
        f"Speed limit {SLOW_MPH} mph or under, of roads with a known limit",
        weight=2,
        condition=is_slow,
        of=posted,
    ),
    Average(
        "lanes",
        "Lanes",
        "Average lanes of the roads, where fewer is better",
        weight=1,
        value=lambda e: e.get("lane_count", 1),
        of=roads,
        best=1,
        half_score=3,
    ),
    Near(
        "near_help",
        "Near help",
        f"Within {surroundings.HELP_MI} mi (a ~15 minute walk) of a business or other place",
        weight=1,
        layer="help",
        distance=surroundings.HELP_MI * METERS_PER_MILE,
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


def edge_scores(edges: list[Edge]):
    """Each road segment's 0-100 score, from only the metrics that apply to a segment on its own (like traffic and surface, but not turns or surroundings), or None if none of them do."""
    return [_edge_score(e) for e in edges]


def _edge_score(edge: Edge):
    weighted = [
        (s, m.weight)
        for m in METRICS
        if m.weight and (s := m.score_edge(edge)) is not None
    ]
    if not weighted:
        return None
    return 100 * sum(s * w for s, w in weighted) / sum(w for _, w in weighted)


def score(ride: Ride):
    values = {m.key: m.measure(ride) for m in METRICS}
    weighted = [
        (m.score(values[m.key]), m.weight)
        for m in METRICS
        if m.weight and values[m.key] is not None
    ]
    total = 100 * sum(s * w for s, w in weighted) / sum(w for _, w in weighted)
    return Scorecard(values, total)
