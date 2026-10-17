from typing import cast

import pytest

from pleasant_rides.models import Point
from pleasant_rides.scoring import METRICS, Ride, Surroundings, score

POINTS = (Point(40.0, -74.0), Point(40.01, -74.0))

BIKE_PATH = {"length": 1.0, "use": "cycleway", "road_class": "service_other"}
BUSY_ROAD = {
    "length": 1.0,
    "use": "road",
    "road_class": "primary",
    "speed_limit": 64,
    "lane_count": 4,
}


class FakeSurroundings:
    """Every route is fully green etc., and passes one of everything."""

    def share_near(self, points, layer, distance):
        return 1.0

    def count_near(self, points, layer, distance):
        return 1


def measure(edges, surroundings=None):
    return score(Ride(POINTS, edges, cast(Surroundings | None, surroundings))).values


def test_share_of_distance():
    values = measure([BIKE_PATH, BUSY_ROAD])
    assert values["distance_km"] == 2
    assert values["low_traffic"] == 0.5


def test_share_only_counts_the_edges_it_applies_to():
    # the bike path has no speed limit, so only the road counts
    values = measure([BIKE_PATH, BUSY_ROAD])
    assert values["slow"] == 0
    assert values["few_lanes"] == 0


def test_share_without_applicable_edges_is_none():
    assert measure([BIKE_PATH])["slow"] is None


def test_turns_per_km():
    edges = [
        {**BIKE_PATH, "begin_heading": 0, "end_heading": 0},
        # a right turn
        {**BIKE_PATH, "begin_heading": 90, "end_heading": 90},
        # a bend, not a turn
        {**BIKE_PATH, "begin_heading": 110, "end_heading": 110},
        # turns across north are measured the short way around
        {**BIKE_PATH, "begin_heading": 350, "end_heading": 350},
    ]
    assert measure(edges)["turns_per_km"] == pytest.approx(2 / 4)


def test_wrong_way_on_a_one_way_isnt_rideable():
    wrong_way = {**BIKE_PATH, "forward": True, "traversability": "backward"}
    assert measure([BIKE_PATH, wrong_way])["rideable"] == 0.5


def test_surroundings_metrics_are_left_out_without_surroundings():
    values = measure([BIKE_PATH])
    assert values["green"] is None
    assert values["sights_per_km"] is None


def test_surroundings_metrics():
    values = measure([BIKE_PATH], FakeSurroundings())
    assert values["green"] == 1
    assert values["sights_per_km"] == 1


def test_total_is_a_weighted_average_of_what_applies():
    # a bike path scores perfectly on everything that applies to it, without surroundings or roads
    assert score(Ride(POINTS, [BIKE_PATH], None)).total == pytest.approx(100)


def test_busier_routes_score_lower():
    calm = score(Ride(POINTS, [BIKE_PATH, BIKE_PATH], None)).total
    busy = score(Ride(POINTS, [BIKE_PATH, BUSY_ROAD], None)).total
    assert busy < calm


def test_metric_keys_are_unique():
    keys = [m.key for m in METRICS]
    assert len(keys) == len(set(keys))
