import json

import pytest

from pleasant_rides import bike_lanes as b
from pleasant_rides import missing_lanes as m
from tests.test_bike_lanes import _lanes


def test_missing():
    nyc = _lanes(
        # two halves of one block, neither in OpenStreetMap, so one task
        [(0, 0), (100, 0)],
        [(100, 0), (200, 0)],
        # in OpenStreetMap
        [(0, 500), (200, 500)],
        # too short to be worth a task
        [(0, 1000), (20, 1000)],
    )
    nyc["name"] = ["1 AV (E 1 ST to E 2 ST)", "1 AV (E 2 ST to E 3 ST)", None, None]
    compared = b.compare({b.NYC: nyc, b.OSM: _lanes([(0, 505), (200, 505)])})

    tasks = m.missing(compared, b.NYC, b.OSM)
    assert len(tasks) == 1
    task = tasks.iloc[0]
    assert task["length_m"] == pytest.approx(200, rel=0.01)
    assert task["category"] == b.PROTECTED
    assert task["names"] == "1 AV (E 1 ST to E 2 ST); 1 AV (E 2 ST to E 3 ST)"
    assert tasks.crs == "EPSG:4326"


def test_to_geojson():
    compared = b.compare({b.NYC: _lanes([(0, 0), (100, 0)]), b.OSM: _lanes()})
    collection = json.loads(m.to_geojson(m.missing(compared, b.NYC, b.OSM)))
    assert collection["type"] == "FeatureCollection"
    [feature] = collection["features"]
    assert feature["geometry"]["type"] == "LineString"
    assert set(feature["properties"]) == {"category", "names", "ids", "length_m"}
