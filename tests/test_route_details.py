"""Tests for what the route page says about a route."""

import pytest

from pleasant_rides.route_details import (
    credit,
    elevation_profile,
    format_value,
    mix,
    route_segments,
    stretches,
)
from pleasant_rides.scoring import METRICS, Scorecard
from pleasant_rides.units import KM_PER_MILE, METERS_PER_FOOT

ONE_MILE = KM_PER_MILE
BY_KEY = {m.key: m for m in METRICS}


def road(length: float = ONE_MILE, **attributes: object):
    return {"length": length, "use": "road", "road_class": "residential", **attributes}


def test_route_segments_describe_and_score_each_edge():
    [segment] = route_segments([road(lane_count=2)])
    assert segment.length == ONE_MILE
    assert segment.description == "residential road, 2 lanes"
    assert segment.score is not None


def test_stretches_merge_consecutive_edges_that_are_alike():
    first, second, third = stretches(
        [
            road(max_upward_grade=2),
            road(max_upward_grade=7),
            {"length": ONE_MILE, "use": "cycleway"},
            road(),
        ]
    )
    assert first.start_mi == 0
    assert first.miles == pytest.approx(2)
    assert first.steepest_grade == 7
    assert second.description == "cycleway"
    assert second.start_mi == pytest.approx(2)
    # alike, but not consecutive
    assert third.description == first.description


def test_stretches_keep_speed_limits_apart_and_in_mph():
    slow, fast = stretches([road(speed_limit=40), road(speed_limit=72)])
    assert slow.speed_limit_mph == 25
    assert fast.speed_limit_mph == 45


def test_stretch_score_is_weighted_by_length():
    edges = [road(max_upward_grade=0), road(length=3 * ONE_MILE, max_upward_grade=9)]
    [stretch] = stretches(edges)
    [gentle, steep] = route_segments(edges)
    assert gentle.score is not None and steep.score is not None
    assert stretch.score == pytest.approx((gentle.score + 3 * steep.score) / 4)


def test_stretches_of_nothing():
    assert stretches([]) == []


def test_mix_adds_up_the_miles_of_each_kind_most_first():
    edges = [
        road(surface="paved_smooth"),
        road(length=3 * ONE_MILE, surface="gravel"),
        road(surface="paved_smooth"),
        road(),
    ]
    assert mix(edges, lambda e: e.get("surface")) == [
        ("gravel", pytest.approx(3)),
        ("paved_smooth", pytest.approx(2)),
        (None, pytest.approx(1)),
    ]


def test_elevation_profile_is_in_feet_at_each_edges_midpoint():
    profile = elevation_profile(
        [
            road(mean_elevation=10),
            road(),
            road(mean_elevation=20),
        ]
    )
    assert profile == [
        {
            "mile": pytest.approx(0.5),
            "elevation_ft": pytest.approx(10 / METERS_PER_FOOT),
        },
        {
            "mile": pytest.approx(2.5),
            "elevation_ft": pytest.approx(20 / METERS_PER_FOOT),
        },
    ]


def test_elevation_profile_is_thinned_out_for_long_routes():
    edges = [road(mean_elevation=i) for i in range(5000)]
    assert len(elevation_profile(edges, max_points=500)) <= 500


@pytest.mark.parametrize(
    "key,value,expected",
    [
        ("low_traffic", 0.456, "46%"),
        ("distance_mi", 12.34, "12.3"),
        ("detour", 1.5, "1.50"),
        ("low_traffic", None, "n/a"),
    ],
)
def test_format_value(key: str, value: float | None, expected: str):
    assert format_value(BY_KEY[key], value) == expected


def test_credit_covers_only_the_metrics_that_count_and_apply():
    card = Scorecard({"low_traffic": 0.5, "slow": None, "distance_mi": 10}, 50)
    assert credit(card, BY_KEY["low_traffic"]) == 0.5
    # no roads with a known speed limit
    assert credit(card, BY_KEY["slow"]) is None
    # only shown, not scored
    assert credit(card, BY_KEY["distance_mi"]) is None
