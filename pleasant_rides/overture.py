"""Reads features from Overture Maps' GeoParquet files on S3, by map tile, with only the columns the surroundings need.

This is kept apart from `surroundings` (which decides which of these features count, and measures routes against them) so that the cached tiles only need refetching when what's read here changes, or Overture puts out a new release.
"""

import asyncio
import io
import threading
from functools import cache

import httpx
import mercantile
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from overturemaps import core
from pyarrow import fs

# Overture type -> the columns read
COLUMNS = {
    "place": ["id", "geometry", "basic_category", "confidence", "operating_status"],
    "land_cover": ["id", "geometry", "subtype"],
    "land_use": ["id", "geometry", "subtype"],
    "water": ["id", "geometry", "subtype", "class"],
    "segment": ["id", "geometry", "class"],
}
# the only roads read, since there are far too many to read them all; a superset of the ones `surroundings` counts as busy, so that it can change which those are without refetching
ROAD_CLASSES = ["motorway", "trunk", "primary", "secondary"]

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


def latest_release():
    """Overture's latest release, e.g. "2026-09-23.1"."""
    return core.get_latest_release()


def _files(release: str, overture_type: str, bbox: tuple[float, ...]):
    """The S3 paths of Overture's files with features of `overture_type` in `bbox`."""
    with _INDEX_LOCK:
        index = _stac_index(release)
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
    release: str,
    overture_type: str,
    bbox: tuple[float, ...],
    columns: list[str],
    keep: pc.Expression | None = None,
):
    """The features in `bbox`, with only `columns`, since places have a lot of them. `keep` filters the features as they're read, so the ones that aren't needed (like all the minor roads) aren't kept in memory."""
    files = _files(release, overture_type, bbox)
    if not files:
        return None
    condition = _overlaps(bbox) if keep is None else _overlaps(bbox) & keep
    with _READS:
        return _dataset(files).to_table(columns=columns, filter=condition)


async def get_tile(release: str, x: int, y: int, zoom: int):
    """Overture type -> its features in a map tile, or None if it has none there, read in parallel."""
    bbox = tuple(mercantile.bounds(x, y, zoom))
    roads = pc.field("class").isin(ROAD_CLASSES)
    tables = await asyncio.gather(
        *(
            asyncio.to_thread(
                _read,
                release,
                overture_type,
                bbox,
                columns,
                roads if overture_type == "segment" else None,
            )
            for overture_type, columns in COLUMNS.items()
        )
    )
    return dict(zip(COLUMNS, tables))
