import json

import pydeck as pdk
import pytest

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


def test_compact_deck():
    layer = pdk.Layer("PathLayer", [{"path": [[-73.9, 40.7], [-73.8, 40.8]]}])
    deck = s.CompactDeck(layers=[layer])
    assert "\n" not in deck.to_json()
    assert json.loads(deck.to_json()) == json.loads(pdk.Deck(layers=[layer]).to_json())


def connected():
    """NYC Open Data's lanes: two connected ones that OpenStreetMap has, and one far away that it doesn't."""
    return b.compare(
        {
            b.NYC: _lanes(
                [(0, 0), (100, 0)], [(100, 0), (200, 0)], [(0, 1000), (100, 1000)]
            ),
            b.OSM: _lanes([(0, 5), (200, 5)]),
        }
    )[b.NYC]


def test_map_lanes_merges_connected_lanes_that_are_alike():
    lanes = s.map_lanes(connected(), [b.OSM])
    assert len(lanes) == 2
    merged = lanes.loc[lanes[b.OSM] == 1].iloc[0]
    assert len(merged["path"]) == 2
    (west, _), (east, _) = sorted(merged["path"])
    # ~200 m apart, in degrees of longitude
    assert east - west == pytest.approx(200 / 84_000, rel=0.05)


def test_map_lanes_keeps_lanes_that_differ_apart():
    frame = connected()
    frame.loc[1, "category"] = b.PAINTED
    assert len(s.map_lanes(frame, [b.OSM])) == 3
