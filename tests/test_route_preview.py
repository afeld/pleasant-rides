from pleasant_rides.map import Segment, build_map
from pleasant_rides.models import Point, Route
from pleasant_rides.route_preview import RoutePreview, step_data
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
    RoutePreview(step_data(POINTS, [step(100)], SEGMENTS), "test-token").add_to(m)
    html = m.get_root().render()
    assert '"test-token"' in html
    assert "Preview route" in html
