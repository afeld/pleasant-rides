from urllib.parse import parse_qs, urlparse

import gpxpy
import pytest

from pleasant_rides.models import Point, Route
from pleasant_rides.route_export import (
    MAX_WAYPOINTS,
    MAX_WAYPOINTS_MOBILE,
    allows_file_export,
    google_maps_url,
    gpx_filename,
    is_mobile,
    to_gpx,
)

# evenly spaced going north
POINTS = tuple(Point(40.0 + i / 1000, -73.0) for i in range(101))
ROUTE = Route("Valhalla", "Primary", POINTS)


def query(url: str):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def test_gpx_keeps_every_point_in_order():
    gpx = gpxpy.parse(to_gpx(ROUTE))
    [track] = gpx.tracks
    assert track.name == "Valhalla: Primary"
    assert [(p.latitude, p.longitude) for p in track.segments[0].points] == [
        (p.lat, p.lon) for p in POINTS
    ]


@pytest.mark.parametrize(
    "provider, expected", [("Valhalla", True), ("Google Maps", False)]
)
def test_allows_file_export(provider: str, expected: bool):
    assert allows_file_export(Route(provider, "Primary", POINTS)) is expected


def test_gpx_filename_is_safe():
    route = Route("Google Maps", "Best route via Empire State Trl/9A", POINTS)
    assert gpx_filename(route) == "google-maps-best-route-via-empire-state-trl-9a.gpx"


def test_google_maps_url_starts_navigation_by_bike():
    params = query(google_maps_url(ROUTE))
    assert params["api"] == "1"
    assert params["travelmode"] == "bicycling"
    assert params["dir_action"] == "navigate"
    assert params["origin"] == "40.0,-73.0"
    assert params["destination"] == "40.1,-73.0"


@pytest.mark.parametrize("limit", [MAX_WAYPOINTS, MAX_WAYPOINTS_MOBILE])
def test_google_maps_waypoints_are_spaced_evenly(limit: int):
    waypoints = query(google_maps_url(ROUTE, limit))["waypoints"].split("|")
    assert len(waypoints) == limit
    lats = [float(waypoint.split(",")[0]) for waypoint in waypoints]
    step = 0.1 / (limit + 1)
    # each snaps to the route's next point, up to 0.001° further along
    assert lats == pytest.approx(
        [40 + step * (i + 1) for i in range(limit)], abs=0.0015
    )


def test_google_maps_url_without_points_between_the_ends():
    route = Route("Valhalla", "Primary", (POINTS[0], POINTS[-1]))
    assert "waypoints" not in query(google_maps_url(route))


def test_google_maps_url_fits_the_length_limit():
    # https://developers.google.com/maps/documentation/urls/get-started
    points = tuple(Point(40.123456789, -73.123456789 + i / 1000) for i in range(100))
    assert len(google_maps_url(Route("Valhalla", "Primary", points))) < 2048


@pytest.mark.parametrize(
    "user_agent, expected",
    [
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148", True),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile Safari/537.36", True),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15", False),
        (None, False),
    ],
)
def test_is_mobile(user_agent: str | None, expected: bool):
    assert is_mobile(user_agent) is expected
