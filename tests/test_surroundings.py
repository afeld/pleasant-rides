import pyarrow as pa
import shapely
from pyproj import CRS, Transformer

from pleasant_rides.surroundings import HELP_M, _bbox, _layers


def table(**columns):
    geometries = [shapely.Point(i, i) for i in range(len(next(iter(columns.values()))))]
    return pa.table({"geometry": shapely.to_wkb(geometries), **columns})


def test_layers():
    places = table(
        basic_category=["museum", "dentist", "museum", "museum"],
        confidence=[0.9, 0.9, 0.3, 0.9],
        operating_status=[None, None, None, "permanently_closed"],
    )
    land_cover = table(subtype=["forest", "barren"])
    land_use = table(subtype=["park", "residential"])
    water = table(
        subtype=["river", "river", "stream"], **{"class": ["river", "ditch", "stream"]}
    )

    busy_roads = table(**{"class": ["motorway", "primary"]})

    layers = _layers(places, land_cover, land_use, water, busy_roads)

    assert len(layers["green"]) == 2
    assert len(layers["water"]) == 1
    # open, confident places
    assert len(layers["sights"]) == 1
    assert len(layers["help"]) == 2
    assert len(layers["busy_roads"]) == 2


def test_layers_without_data():
    layers = _layers(None, None, None, None, None)
    assert all(len(geoms) == 0 for geoms in layers.values())


def test_bbox_covers_help_distance():
    crs = CRS.from_proj4("+proj=aeqd +lat_0=40 +lon_0=-74 +units=m")
    to_local = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    west, south, east, north = _bbox([40.0], [-74.0], crs, to_local)
    # ~1 km is ~0.009° of latitude
    assert north - 40.0 > HELP_M / 111_000 * 0.99
    assert west < -74.0 < east and south < 40.0 < north


def test_read_keeps_only_matching_features(monkeypatch):
    from pleasant_rides import surroundings
    from pleasant_rides.surroundings import _read

    roads = table(
        **{"class": ["motorway", "residential", "primary"]}, id=["a", "b", "c"]
    )
    monkeypatch.setattr(
        surroundings.core,
        "record_batch_reader",
        lambda *args, **kwargs: pa.RecordBatchReader.from_batches(
            roads.schema, roads.to_batches(max_chunksize=2)
        ),
    )
    read = _read(
        "segment", (0, 0, 1, 1), ["geometry", "class"], surroundings._busy_road()
    )
    assert read is not None
    assert read.column_names == ["geometry", "class"]
    assert read["class"].to_pylist() == ["motorway", "primary"]
