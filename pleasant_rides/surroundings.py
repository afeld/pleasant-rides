"""What's around a set of routes, from Overture Maps: nature, water, sights, and places to get help.

Overture's data lives in GeoParquet files on S3, so this downloads the features in the map tiles near the routes, then measures each route against them locally. Tiles (rather than one box around all the routes) keep long or diagonal routes from pulling in everything between them, and let each tile be cached on its own, so routes that overlap ones seen before only download what's new.
"""

import asyncio
import io
import threading
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from functools import cache, cached_property

import httpx
import mercantile
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import shapely
from overturemaps import core
from pyarrow import fs
from pyproj import CRS, Transformer

from .models import Point

# https://docs.overturemaps.org/guides/base/
GREEN_LAND_COVER = ["forest", "shrub", "grass", "wetland", "mangrove", "moss"]
GREEN_LAND_USE = ["park", "protected"]
# leaves out small streams and drainage, which are often just a culvert under the road
WATER_SUBTYPES = ["ocean", "lake", "pond", "reservoir", "river", "canal", "water"]
NOT_WATER_CLASSES = ["wastewater", "ditch", "drain", "dock"]
# Overture's `basic_category` values for places worth looking at
SIGHTS = [
    "park",
    "garden",
    "nature_reserve",
    "national_park",
    "forest",
    "beach",
    "lake",
    "river",
    "waterfall",
    "mountain",
    "island",
    "historic_site",
    "monument",
    "memorial_site",
    "sculpture_statue",
    "street_art",
    "public_fountain",
    "public_plaza",
    "museum",
    "art_gallery",
    "cultural_center",
    "lighthouse",
    "castle",
    "fort",
    "bridge",
    "pier",
    "marina",
    "farmers_market",
    "winery",
    "zoo",
    "aquarium",
]
# Overture's road classes with heavy, loud traffic; secondary roads are left out, since nearly every city route is close to one
BUSY_ROAD_CLASSES = ["motorway", "trunk", "primary"]
# places below this are often duplicates or no longer there
MIN_CONFIDENCE = 0.6

# how close a route needs to be to each kind of feature (meters)
GREEN_M = 30  # alongside
WATER_M = 100  # in view
SIGHT_M = 50
HELP_M = 1000  # a ~15 minute walk
QUIET_M = 50  # within earshot of heavy traffic

SAMPLE_M = 20  # spacing of the points along a route that are checked

# ~10 km across at the equator, ~7 km in New York; each read from Overture takes a couple of seconds however small, so smaller tiles would mean many more reads
TILE_ZOOM = 12


def _project(geoms: np.ndarray, transformer: Transformer):
    return shapely.transform(
        geoms, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
    )


# Overture's files are on S3, which handles parallel reads fine, but there are a lot of them per set of routes (a few per tile)
_READS = threading.BoundedSemaphore(8)
_INDEX_LOCK = threading.Lock()


@cache
def _stac_index(release: str):
    """Overture's index of its files and the areas each covers. Downloaded once per release, since the overturemaps library downloads it again for every read, which gets rate-limited once there are a few tiles."""
    response = httpx.get(
        f"https://stac.overturemaps.org/{release}/collections.parquet", timeout=60
    )
    response.raise_for_status()
    return pq.read_table(io.BytesIO(response.content))


def _overlaps(bbox: tuple[float, ...]):
    """Whether a row's `bbox` overlaps `bbox`, as in both Overture's index and its data."""
    xmin, ymin, xmax, ymax = bbox
    return (
        (pc.field("bbox", "xmin") < xmax)
        & (pc.field("bbox", "xmax") > xmin)
        & (pc.field("bbox", "ymin") < ymax)
        & (pc.field("bbox", "ymax") > ymin)
    )


def _files(overture_type: str, bbox: tuple[float, ...]):
    """The S3 paths of Overture's files with features of `overture_type` in `bbox`."""
    with _INDEX_LOCK:
        index = _stac_index(core.get_latest_release())
    found = index.filter(
        (pc.field("collection") == overture_type)
        & (pc.field("type") == "Feature")
        & _overlaps(bbox)
    )
    return [
        asset["aws"]["alternate"]["s3"]["href"].removeprefix("s3://")
        for asset in found["assets"].to_pylist()
    ]


def _dataset(files: list[str]):
    return ds.dataset(
        files, filesystem=fs.S3FileSystem(anonymous=True, region="us-west-2")
    )


def _read(
    overture_type: str,
    bbox: tuple[float, ...],
    columns: list[str],
    keep: pc.Expression | None = None,
):
    """The features in `bbox`, with only `columns`, since places have a lot of them. `keep` filters the features as they're read, so the ones that aren't needed (like all the minor roads) aren't kept in memory."""
    files = _files(overture_type, bbox)
    if not files:
        return None
    condition = _overlaps(bbox) if keep is None else _overlaps(bbox) & keep
    with _READS:
        return _dataset(files).to_table(columns=columns, filter=condition)


# a map tile, as (x, y, zoom)
Tile = tuple[int, int, int]


@dataclass(frozen=True)
class Features:
    """Overture features in (lon, lat), with their IDs, so that ones found in more than one tile are only counted once."""

    ids: np.ndarray
    geometries: np.ndarray

    def __len__(self):
        return len(self.ids)

    @staticmethod
    def combine(parts: Sequence["Features"]):
        """The features in any of `parts`, each once."""
        ids = np.concatenate([p.ids for p in parts])
        geometries = np.concatenate([p.geometries for p in parts])
        _, first = np.unique(ids, return_index=True)
        first.sort()
        return Features(ids[first], geometries[first])


_NO_FEATURES = Features(np.array([], dtype=object), np.array([], dtype=object))


def _features(table: pa.Table | None, condition: pc.Expression):
    if table is None:
        return _NO_FEATURES
    kept = table.filter(condition)
    wkb = kept["geometry"].to_numpy(zero_copy_only=False)
    return Features(kept["id"].to_numpy(zero_copy_only=False), shapely.from_wkb(wkb))


def _line(points: Sequence[Point]):
    """The route as a LineString in (lon, lat)."""
    return shapely.LineString([(lon, lat) for lat, lon in points])


@dataclass(frozen=True)
class Surroundings:
    # a local projection in meters, centered on the routes
    crs: CRS
    # layer name -> features, in `crs`
    layers: dict[str, np.ndarray]

    @cached_property
    def _trees(self):
        return {name: shapely.STRtree(geoms) for name, geoms in self.layers.items()}

    def line(self, points: Sequence[Point]):
        """The route as a LineString in meters."""
        transformer = Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        return _project(np.array([_line(points)]), transformer)[0]

    def share_near(self, points: Sequence[Point], layer: str, distance: float):
        """The share (0-1) of the route's distance that's within `distance` meters of a feature in `layer`."""
        line = self.line(points)
        samples = shapely.line_interpolate_point(
            line, np.arange(0, line.length, SAMPLE_M)
        )
        if not len(samples):
            return None
        near, _ = self._trees[layer].query(
            samples, predicate="dwithin", distance=distance
        )
        return len(np.unique(near)) / len(samples)

    def count_near(self, points: Sequence[Point], layer: str, distance: float):
        """How many features in `layer` are within `distance` meters of the route."""
        line = self.line(points)
        return len(
            self._trees[layer].query(line, predicate="dwithin", distance=distance)
        )


async def get_tile(x: int, y: int, zoom: int):
    """Layer name -> the features in a map tile."""
    return _layers(*await _read_all(tuple(mercantile.bounds(x, y, zoom))))


GetTile = Callable[[int, int, int], Awaitable[dict[str, Features]]]


async def get_surroundings(
    routes: Sequence[Sequence[Point]], get_tile: GetTile = get_tile
):
    """Fetches the features around `routes`, each a list of (lat, lon) points, with `get_tile()`, so the tiles can be cached."""
    lats = [lat for points in routes for lat, _ in points]
    lons = [lon for points in routes for _, lon in points]
    # a local projection in meters, so distances can be measured directly
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={np.mean(lats)} +lon_0={np.mean(lons)} +units=m"
    )
    to_local = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    tiles = await asyncio.gather(
        *(get_tile(*tile) for tile in _tiles(routes, lats, lons, crs, to_local))
    )
    return Surroundings(
        crs,
        {
            name: _project(
                Features.combine([tile[name] for tile in tiles]).geometries, to_local
            )
            for name in tiles[0]
        },
    )


def _tiles(
    routes: Sequence[Sequence[Point]],
    lats: list[float],
    lons: list[float],
    crs: CRS,
    to_local: Transformer,
) -> list[Tile]:
    """The tiles with anything within HELP_M of any of the routes."""
    lines = _project(np.array([_line(points) for points in routes]), to_local)
    corridor = shapely.union_all(shapely.buffer(lines, HELP_M))
    candidates = list(
        mercantile.tiles(*_bbox(lats, lons, crs, to_local), zooms=TILE_ZOOM)
    )
    boxes = _project(
        np.array([shapely.box(*mercantile.bounds(t)) for t in candidates]), to_local
    )
    return [
        (t.x, t.y, t.z)
        for t, near in zip(candidates, shapely.intersects(boxes, corridor))
        if near
    ]


def _bbox(lats: list[float], lons: list[float], crs: CRS, to_local: Transformer):
    """A (lon, lat) box around the points, wide enough to include anything within HELP_M of them."""
    to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    x, y = to_local.transform(lons, lats)
    return to_lonlat.transform_bounds(
        min(x) - HELP_M, min(y) - HELP_M, max(x) + HELP_M, max(y) + HELP_M
    )


async def _read_all(bbox: tuple[float, ...]):
    """The places, land cover, land use, water, and busy roads in `bbox`, read in parallel, with their IDs."""
    return await asyncio.gather(
        asyncio.to_thread(
            _read,
            "place",
            bbox,
            ["id", "geometry", "basic_category", "confidence", "operating_status"],
        ),
        asyncio.to_thread(_read, "land_cover", bbox, ["id", "geometry", "subtype"]),
        asyncio.to_thread(_read, "land_use", bbox, ["id", "geometry", "subtype"]),
        asyncio.to_thread(_read, "water", bbox, ["id", "geometry", "subtype", "class"]),
        asyncio.to_thread(
            _read, "segment", bbox, ["id", "geometry", "class"], _busy_road()
        ),
    )


def _busy_road():
    return pc.field("class").isin(BUSY_ROAD_CLASSES)


def _layers(
    places: pa.Table | None,
    land_cover: pa.Table | None,
    land_use: pa.Table | None,
    water: pa.Table | None,
    busy_roads: pa.Table | None,
):
    """Layer name -> its features."""
    open_place = (pc.field("confidence") >= MIN_CONFIDENCE) & (
        pc.field("operating_status").is_null()
        | (pc.field("operating_status") != "permanently_closed")
    )
    return {
        "green": Features.combine(
            [
                _features(land_cover, pc.field("subtype").isin(GREEN_LAND_COVER)),
                _features(land_use, pc.field("subtype").isin(GREEN_LAND_USE)),
            ]
        ),
        "water": _features(
            water,
            pc.field("subtype").isin(WATER_SUBTYPES)
            & ~pc.field("class").isin(NOT_WATER_CLASSES),
        ),
        "sights": _features(
            places, open_place & pc.field("basic_category").isin(SIGHTS)
        ),
        "help": _features(places, open_place),
        "busy_roads": _features(busy_roads, _busy_road()),
    }
