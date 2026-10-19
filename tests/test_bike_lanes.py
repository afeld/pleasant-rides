import pytest
import shapely

from pleasant_rides import bike_lanes as b


@pytest.mark.parametrize(
    "tags, category",
    [
        ({"highway": "cycleway"}, b.PROTECTED),
        ({"highway": "cycleway", "cycleway": "crossing"}, b.CONNECTOR),
        ({"highway": "footway", "bicycle": "designated"}, b.PROTECTED),
        ({"highway": "footway"}, None),
        ({"highway": "secondary", "cycleway:left": "track"}, b.PROTECTED),
        ({"highway": "secondary", "cycleway:right": "lane"}, b.PAINTED),
        ({"highway": "residential", "cycleway:both": "shared_lane"}, b.SHARED),
        ({"highway": "residential", "bicycle": "designated"}, b.SHARED),
        ({"highway": "residential"}, None),
        ({"highway": "construction", "cycleway": "lane"}, None),
    ],
)
def test_osm_category(tags, category):
    assert b.osm_category(tags) == category


BIKES_DESIGNATED = [{"access_type": "designated", "when": {"mode": ["bicycle"]}}]


@pytest.mark.parametrize(
    "road_class, subclass, restrictions, category",
    [
        ("cycleway", None, None, b.PROTECTED),
        ("footway", "cycle_crossing", None, b.CONNECTOR),
        ("footway", "crosswalk", BIKES_DESIGNATED, b.CONNECTOR),
        ("path", None, BIKES_DESIGNATED, b.PROTECTED),
        ("residential", None, BIKES_DESIGNATED, b.SHARED),
        (
            "residential",
            None,
            [{"access_type": "designated", "when": {"mode": ["bus"]}}],
            None,
        ),
        ("residential", None, None, None),
    ],
)
def test_overture_category(road_class, subclass, restrictions, category):
    assert b.overture_category(road_class, subclass, restrictions) == category


def test_parse_osm():
    data = {
        "osm3s": {"timestamp_osm_base": "2026-01-01T00:00:00Z"},
        "elements": [
            {
                "id": 1,
                "tags": {"highway": "cycleway", "name": "Hudson River Greenway"},
                "timestamp": "2025-06-01T12:00:00Z",
                "geometry": [{"lat": 40.7, "lon": -74.0}, {"lat": 40.71, "lon": -74.0}],
            },
            {
                "id": 2,
                "tags": {"highway": "residential"},
                "geometry": [{"lat": 40.7, "lon": -74.0}, {"lat": 40.71, "lon": -74.0}],
            },
        ],
    }
    lanes, as_of = b.parse_osm(data)
    assert as_of == "2026-01-01T00:00:00Z"
    assert lanes["id"].tolist() == ["way/1"]
    assert lanes["category"].tolist() == [b.PROTECTED]
    assert lanes["updated"].tolist() == ["2025-06-01T12:00:00Z"]


def test_parse_nyc():
    data = {
        "features": [
            {
                "properties": {
                    "segmentid": "1",
                    "street": "1 AV",
                    "fromstreet": "E 1 ST",
                    "tostreet": "E 20 ST",
                    "facilitycl": "II",
                },
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": [
                        [[-73.98, 40.73], [-73.97, 40.74]],
                        [[-73.97, 40.74], [-73.96, 40.75]],
                    ],
                },
            }
        ]
    }
    lanes = b.parse_nyc(data)
    # one row per line
    assert len(lanes) == 2
    assert set(lanes.geom_type) == {"LineString"}
    assert lanes["name"].iloc[0] == "1 AV (E 1 ST to E 20 ST)"
    assert lanes["category"].iloc[0] == b.PAINTED


def _lanes(*lines, category=b.PROTECTED):
    """Lanes from lines in meters, near the city, in lat/lon like the sources'."""
    frame = b._frame(
        [{"id": str(i), "name": None, "category": category} for i in range(len(lines))],
        [shapely.LineString(line) for line in lines],
    )
    frame = frame.set_crs(b.METRIC_CRS, allow_override=True)
    frame.geometry = frame.geometry.translate(585_000, 4_510_000)
    return frame.to_crs("EPSG:4326")


def test_compare():
    compared = b.compare(
        {
            # 100 m along the x axis
            "a": _lanes([(0, 0), (100, 0)]),
            # 10 m from its first half, so within 20 m of its first ~two thirds, plus a lane far away
            "b": _lanes([(0, 10), (50, 10)], [(0, 1000), (100, 1000)]),
        }
    )
    a, other = compared["a"], compared["b"]
    assert a["length_m"].iloc[0] == pytest.approx(100, rel=0.01)
    assert a["b"].iloc[0] == pytest.approx(0.67, abs=0.05)
    assert other["a"].tolist() == [1, 0]

    overlap = b.overlap(compared)
    assert overlap.loc["b", "a"] == pytest.approx(50 / 150, rel=0.01)
    assert b.lengths_by_category(compared).loc[b.PROTECTED, "b"] == pytest.approx(
        0.15, rel=0.01
    )
