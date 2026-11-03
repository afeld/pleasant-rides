import json

from pleasant_rides import bike_lanes as b
from pleasant_rides import lane_selection as s
from tests.test_bike_lanes import _lanes


def compared():
    return b.compare(
        {
            # one lane OpenStreetMap has too, and one it doesn't
            b.NYC: _lanes([(0, 0), (100, 0)], [(0, 1000), (100, 1000)]),
            b.OSM: _lanes([(0, 5), (100, 5)]),
            b.OVERTURE: _lanes([(0, 0), (100, 0)], category=b.PAINTED),
        }
    )


def test_select_by_source_and_category():
    selected = s.select(compared(), [b.NYC, b.OVERTURE], [b.PROTECTED], False)
    assert list(selected) == [b.NYC, b.OVERTURE]
    assert len(selected[b.NYC]) == 2
    assert selected[b.OVERTURE].empty


def test_select_only_what_the_others_do_not_have():
    selected = s.select(compared(), [b.NYC, b.OSM], b.CATEGORIES, True)
    assert list(selected[b.NYC]["id"]) == ["1"]
    assert selected[b.OSM].empty


def test_to_geojson():
    selected = s.select(compared(), [b.NYC, b.OSM], b.CATEGORIES, False)
    collection = json.loads(s.to_geojson(selected))
    assert collection["type"] == "FeatureCollection"
    features = collection["features"]
    assert len(features) == 3
    assert features[0]["geometry"]["type"] == "LineString"
    # lat/lon, near the city
    lon, lat = features[0]["geometry"]["coordinates"][0]
    assert -75 < lon < -73 and 40 < lat < 41
    assert features[0]["properties"] == {
        "source": b.NYC,
        "id": "0",
        "name": None,
        "category": b.PROTECTED,
        "updated": None,
        "length_m": 100,
    }


def test_to_geojson_with_nothing_selected():
    collection = json.loads(s.to_geojson(s.select(compared(), [], [], False)))
    assert collection == {"type": "FeatureCollection", "features": []}
