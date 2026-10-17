"""What's around a set of routes, from Overture Maps: nature, water, sights, and places to get help.

Overture's data lives in GeoParquet files on S3, so this downloads the features in a box around all of the routes at once, then measures each route against them locally.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import shapely
from overturemaps import core
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
# places below this are often duplicates or no longer there
MIN_CONFIDENCE = 0.6

# how close a route needs to be to each kind of feature (meters)
GREEN_M = 30  # alongside
WATER_M = 100  # in view
SIGHT_M = 50
HELP_M = 1000  # a ~15 minute walk

SAMPLE_M = 20  # spacing of the points along a route that are checked


def _project(geoms: np.ndarray, transformer: Transformer):
    return shapely.transform(
        geoms, lambda xy: np.column_stack(transformer.transform(xy[:, 0], xy[:, 1]))
    )


def _read(overture_type: str, bbox: tuple[float, ...], columns: list[str]):
    reader = core.record_batch_reader(overture_type, bbox, stac=True)
    if reader is None:
        return None
    # only keep the needed columns of each batch, since places have a lot of them
    return pa.Table.from_batches(
        (batch.select(columns) for batch in reader),
        schema=pa.schema([reader.schema.field(c) for c in columns]),
    )


def _geometries(table: pa.Table | None, condition: pc.Expression):
    if table is None:
        return np.array([], dtype=object)
    wkb = table.filter(condition)["geometry"].to_numpy(zero_copy_only=False)
    return shapely.from_wkb(wkb)


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
        return _project(
            np.array([shapely.LineString([(lon, lat) for lat, lon in points])]),
            transformer,
        )[0]

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


async def get_surroundings(routes: Sequence[Sequence[Point]]):
    """Fetches the features around `routes`, each a list of (lat, lon) points."""
    lats = [lat for points in routes for lat, _ in points]
    lons = [lon for points in routes for _, lon in points]
    crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={np.mean(lats)} +lon_0={np.mean(lons)} +units=m"
    )
    to_local = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    # wide enough to include anything within HELP_M of the routes
    x, y = to_local.transform(lons, lats)
    bbox = to_lonlat.transform_bounds(
        min(x) - HELP_M, min(y) - HELP_M, max(x) + HELP_M, max(y) + HELP_M
    )

    places, land_cover, land_use, water = await asyncio.gather(
        asyncio.to_thread(
            _read,
            "place",
            bbox,
            ["geometry", "basic_category", "confidence", "operating_status"],
        ),
        asyncio.to_thread(_read, "land_cover", bbox, ["geometry", "subtype"]),
        asyncio.to_thread(_read, "land_use", bbox, ["geometry", "subtype"]),
        asyncio.to_thread(_read, "water", bbox, ["geometry", "subtype", "class"]),
    )

    open_place = (pc.field("confidence") >= MIN_CONFIDENCE) & (
        pc.field("operating_status").is_null()
        | (pc.field("operating_status") != "permanently_closed")
    )
    layers = {
        "green": np.concatenate(
            [
                _geometries(land_cover, pc.field("subtype").isin(GREEN_LAND_COVER)),
                _geometries(land_use, pc.field("subtype").isin(GREEN_LAND_USE)),
            ]
        ),
        "water": _geometries(
            water,
            pc.field("subtype").isin(WATER_SUBTYPES)
            & ~pc.field("class").isin(NOT_WATER_CLASSES),
        ),
        "sights": _geometries(
            places, open_place & pc.field("basic_category").isin(SIGHTS)
        ),
        "help": _geometries(places, open_place),
    }
    return Surroundings(
        crs, {name: _project(geoms, to_local) for name, geoms in layers.items()}
    )
