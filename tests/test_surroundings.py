import asyncio
import itertools

import mercantile
import numpy as np
import pyarrow as pa
import shapely
from pyproj import CRS, Transformer

from pleasant_rides.models import Point
from pleasant_rides.surroundings import (
    HELP_M,
    TILE_ZOOM,
    _bbox,
    _layers,
    _tiles,
    get_surroundings,
)

# Overture's IDs are unique across feature types
_ids = itertools.count()


def table(**columns):
    count = len(next(iter(columns.values())))
    geometries = [shapely.Point(i, i) for i in range(count)]
    return pa.table(
        {
            "id": [f"id{next(_ids)}" for _ in range(count)],
            "geometry": shapely.to_wkb(geometries),
            **columns,
        }
    )


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

    layers = _layers(
        {
            "place": places,
            "land_cover": land_cover,
            "land_use": land_use,
            "water": water,
            "segment": busy_roads,
        }
    )

    assert len(layers["green"]) == 2
    assert len(layers["water"]) == 1
    # open, confident places
    assert len(layers["sights"]) == 1
    assert len(layers["help"]) == 2
    assert len(layers["busy_roads"]) == 2


def test_layers_without_data():
    layers = _layers(
        dict.fromkeys(["place", "land_cover", "land_use", "water", "segment"])
    )
    assert all(len(geoms) == 0 for geoms in layers.values())


def test_bbox_covers_help_distance():
    crs = CRS.from_proj4("+proj=aeqd +lat_0=40 +lon_0=-74 +units=m")
    to_local = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    west, south, east, north = _bbox([40.0], [-74.0], crs, to_local)
    # ~1 km is ~0.009° of latitude
    assert north - 40.0 > HELP_M / 111_000 * 0.99
    assert west < -74.0 < east and south < 40.0 < north


def local(lats, lons):
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={np.mean(lats)} +lon_0={np.mean(lons)} +units=m"
    )
    return crs, Transformer.from_crs("EPSG:4326", crs, always_xy=True)


def test_tiles_follow_the_route_rather_than_its_bounding_box():
    # a diagonal route ~50 km across
    route = [Point(40.6, -74.1), Point(41.0, -73.7)]
    lats, lons = [lat for lat, _ in route], [lon for _, lon in route]
    tiles = _tiles([route], lats, lons, *local(lats, lons))
    box = list(
        mercantile.tiles(*_bbox(lats, lons, *local(lats, lons)), zooms=TILE_ZOOM)
    )
    assert len(tiles) < len(box) / 2
    # both ends are covered
    for lat, lon in route:
        assert tuple(mercantile.tile(lon, lat, TILE_ZOOM)) in tiles


def test_features_in_several_tiles_are_only_counted_once():
    park = shapely.box(-74.0, 40.0, -73.99, 40.01)

    async def get_tile(x, y, zoom):
        # the same park, in every tile
        return {
            "place": None,
            "land_cover": None,
            "land_use": pa.table(
                {
                    "id": ["park"],
                    "geometry": [shapely.to_wkb(park)],
                    "subtype": ["park"],
                }
            ),
            "water": None,
            "segment": None,
        }

    route = [Point(40.0, -74.0), Point(40.2, -74.0)]
    lats, lons = [lat for lat, _ in route], [lon for _, lon in route]
    assert len(_tiles([route], lats, lons, *local(lats, lons))) > 1
    around = asyncio.run(get_surroundings([route], get_tile))
    assert len(around.layers["green"]) == 1
