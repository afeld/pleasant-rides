from typing import cast

import pytest

from pleasant_rides.metrics import Ride
from pleasant_rides.models import Point
from pleasant_rides.scoring import METRICS, score
from pleasant_rides.surroundings import Surroundings

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
    assert values["lanes"] == 4


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


def test_fewer_lanes_score_better():
    lanes = next(m for m in METRICS if m.key == "lanes")
    one, two, four = (
        {"length": 1.0, "use": "road", "road_class": "residential", "lane_count": n}
        for n in (1, 2, 4)
    )
    # distance-weighted, of roads only
    assert measure([BIKE_PATH, one, four])["lanes"] == 2.5
    assert measure([BIKE_PATH])["lanes"] is None
    assert lanes.score(1) == 1
    assert lanes.score(2) > lanes.score(3) > lanes.score(4) > 0
    assert lanes.score(3) == 0.5


def test_quiet_is_the_share_away_from_busy_roads():
    class NearBusyRoadsHalfTheTime(FakeSurroundings):
        def share_near(self, points, layer, distance):
            return 0.5 if layer == "busy_roads" else 1.0

    assert measure([BIKE_PATH], NearBusyRoadsHalfTheTime())["quiet"] == 0.5
    assert measure([BIKE_PATH])["quiet"] is None


def test_detour_is_distance_vs_a_straight_line():
    detour = next(m for m in METRICS if m.key == "detour")
    # POINTS are ~1.11 km apart, north-south
    assert measure([BIKE_PATH])["detour"] == pytest.approx(1 / 1.11, rel=0.01)
    assert measure([BIKE_PATH, BIKE_PATH, BIKE_PATH])["detour"] == pytest.approx(
        3 / 1.11, rel=0.01
    )
    # direct routes on roads aren't penalized, and longer detours score lower
    assert detour.score(1.1) == detour.score(1.3) == 1
    assert detour.score(2) == 0.5
    assert detour.score(1.5) > detour.score(2) > detour.score(3) > 0


def test_detour_of_a_loop_is_none():
    loop = Ride((POINTS[0], POINTS[1], POINTS[0]), [BIKE_PATH], None)
    assert score(loop).values["detour"] is None
