import folium
import pytest

from pleasant_rides.map import build_map
from pleasant_rides.models import Point, Route

A = Route("Valhalla", "Primary", (Point(40.0, -74.0), Point(40.01, -74.0)))
B = Route("Valhalla", "Alternate 1", (Point(40.0, -74.0), Point(40.0, -74.01)))
C = Route("BRouter", "BRouter (pleasant)", (Point(40.0, -74.0), Point(40.02, -74.02)))


def lines(m: folium.Map):
    return [c for c in _descendants(m) if isinstance(c, folium.PolyLine)]


def _descendants(element):
    for child in element._children.values():
        yield child
        yield from _descendants(child)


def test_one_line_per_route():
    labels = [line.options["routeLabel"] for line in lines(build_map([A, B, C]))]
    assert len(labels) == 3
    assert any("Valhalla: Alternate 1" in label for label in labels)


def test_highlight_draws_the_route_on_top():
    m = build_map([A, B, C], highlight=C)
    *routes, outline, highlight = lines(m)
    assert len(routes) == 3
    assert outline.locations == highlight.locations == [list(p) for p in C.points]
    assert all(line.options["opacity"] == 0.3 for line in routes)


def test_highlight_that_isnt_mapped_isnt_drawn():
    other = Route("Google Maps", "Best route", A.points)
    assert len(lines(build_map([A, B], highlight=other))) == 2


def test_no_routes():
    with pytest.raises(ValueError):
        build_map([])
