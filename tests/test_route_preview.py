import pytest

from pleasant_rides.map import Segment, build_map
from pleasant_rides.models import Point, Route
from pleasant_rides.route_preview import RoutePreview, route_miles, step_data
from pleasant_rides.street_photos import Step

# ~1.1 km north
POINTS = (Point(40.75, -73.98), Point(40.76, -73.98))
SEGMENTS = [Segment(1, 100, "cycleway"), Segment(3, 0, "primary road, 4 lanes")]


def step(along_m: float):
    return Step("photo", POINTS[0], along_m, 0, False, 0)


def test_step_data_matches_steps_to_segments():
    # the first segment is a quarter of the route
    first, second = step_data(POINTS, [step(100), step(500)], SEGMENTS)
    assert first["info"] == "cycleway"
    assert second["info"] == "primary road, 4 lanes"
    assert first["color"] != second["color"]
    assert second["along_mi"] == round(500 / 1609.344, 2)


def test_preview_renders_with_the_token_and_steps():
    route = Route("Valhalla", "Primary", POINTS)
    m = build_map([route], highlight=route, segments=SEGMENTS)
    data = step_data(POINTS, [step(100)], SEGMENTS)
    RoutePreview(data, "test-token", route_miles(POINTS)).add_to(m)
    html = m.get_root().render()
    assert '"test-token"' in html
    assert "Preview route" in html


def test_step_data_marks_gaps_without_photos():
    # the route is ~1,112 m; photos 25 m apart, then none for 500 m, then none for the last ~460 m
    first, before_gap, after_gap = step_data(
        POINTS, [step(0), step(25), step(525)], SEGMENTS
    )
    assert first["gap_behind_mi"] is first["gap_ahead_mi"] is None
    assert before_gap["gap_ahead_mi"] == round(500 / 1609.344, 1)
    assert after_gap["gap_behind_mi"] == round(500 / 1609.344, 1)
    assert after_gap["gap_ahead_mi"] == pytest.approx(0.4, abs=0.05)


def test_step_data_marks_a_gap_at_the_start():
    [only] = step_data(POINTS, [step(400)], SEGMENTS)
    assert only["gap_behind_mi"] == round(400 / 1609.344, 1)


def test_route_miles():
    assert route_miles(POINTS) == pytest.approx(1112 / 1609.344, abs=0.01)


@pytest.mark.parametrize("open", [True, False])
def test_preview_opens_on_load_only_when_asked(open: bool):
    route = Route("Valhalla", "Primary", POINTS)
    m = build_map([route], highlight=route)
    data = step_data(POINTS, [step(100)], SEGMENTS)
    RoutePreview(data, "test-token", route_miles(POINTS), open=open).add_to(m)
    assert f"if ({str(open).lower()}) window.addEventListener" in m.get_root().render()
