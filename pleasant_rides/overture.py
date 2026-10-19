"""Reads features from Overture Maps' GeoParquet files on S3, by map tile, with only the columns the surroundings need.

This is kept apart from `surroundings` (which decides which of these features count, and measures routes against them) so that the cached tiles only need refetching when what's read here changes, or Overture puts out a new release.
"""

import asyncio
import io
import logging
import threading
import time
from collections.abc import Callable

import httpx
import mercantile
import pyarrow as pa
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

BUCKET = "overturemaps-us-west-2"
# Overture's files are on S3, which handles parallel reads fine, but there are a lot of them per set of routes (a few per tile)
_READS = threading.BoundedSemaphore(8)
# after the STAC server fails (e.g. rate-limits us), how long to go without it, reading S3 directly instead
STAC_RETRY_S = 15 * 60

_log = logging.getLogger(__name__)
_stac_lock = threading.Lock()
_stac_indexes: dict[str, pa.Table] = {}
_stac_failed_at: float | None = None


def _s3():
    return fs.S3FileSystem(anonymous=True, region="us-west-2")


def fetch_stac_index(release: str):
    """Overture's index of its files and the areas each covers. The overturemaps library downloads it again for every read, which gets rate-limited once there are a few tiles, so this is downloaded once per release (see `stac_index()`)."""
    response = httpx.get(
        f"https://stac.overturemaps.org/{release}/collections.parquet", timeout=60
    )
    response.raise_for_status()
    return pq.read_table(io.BytesIO(response.content))


def _stac_down():
    return (
        _stac_failed_at is not None
        and time.monotonic() - _stac_failed_at < STAC_RETRY_S
    )


def _stac_failed(what: str, error: Exception):
    global _stac_failed_at
    _stac_failed_at = time.monotonic()
    _log.warning(
        "Couldn't get %s from Overture's STAC server, so reading S3 directly for the next %d minutes: %s",
        what,
        STAC_RETRY_S // 60,
        error,
    )


def stac_index(
    release: str, fetch: Callable[[str], pa.Table] = fetch_stac_index
) -> pa.Table | None:
    """The index for `release`, from `fetch()` (which can be cached), once per process; None if the STAC server is failing, in which case it isn't asked again for STAC_RETRY_S."""
    with _stac_lock:
        if release not in _stac_indexes:
            if _stac_down():
                return None
            try:
                _stac_indexes[release] = fetch(release)
            except httpx.HTTPError as e:
                _stac_failed("its index", e)
                return None
        return _stac_indexes[release]


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
    """Overture's latest release, e.g. "2026-09-23.1", from the STAC server, or the newest one on S3 if that's failing."""
    if not _stac_down():
        try:
            return core.get_latest_release()
        except Exception as e:  # the library wraps every error in a plain Exception
            _stac_failed("the latest release", e)
    releases = _s3().get_file_info(fs.FileSelector(f"{BUCKET}/release/"))
    return max(info.base_name for info in releases)


def _files(index: pa.Table, overture_type: str, bbox: tuple[float, ...]):
    """The S3 paths of Overture's files with features of `overture_type` in `bbox`."""
    found = index.filter(
        (pc.field("collection") == overture_type)
        & (pc.field("type") == "Feature")
        & _overlaps(bbox)
    )
    return [
        asset["aws"]["alternate"]["s3"]["href"].removeprefix("s3://")
        for asset in found["assets"].to_pylist()
    ]


def _dataset(source: str | list[str]):
    return ds.dataset(source, filesystem=_s3())


def _read(
    release: str,
    index: pa.Table | None,
    overture_type: str,
    bbox: tuple[float, ...],
    columns: list[str],
    keep: pc.Expression | None = None,
):
    """The features in `bbox`, with only `columns`, since places have a lot of them. `keep` filters the features as they're read, so the ones that aren't needed (like all the minor roads) aren't kept in memory. Only the files that `index` says cover `bbox` are read; without it, all of the type's files are, which is slower, but still only reads the parts of them in `bbox`."""
    if index is None:
        source = f"{BUCKET}/release/{release}/theme={core.type_theme_map[overture_type]}/type={overture_type}/"
    else:
        source = _files(index, overture_type, bbox)
        if not source:
            return None
    condition = _overlaps(bbox) if keep is None else _overlaps(bbox) & keep
    with _READS:
        return _dataset(source).to_table(columns=columns, filter=condition)


async def get_tile(
    release: str,
    x: int,
    y: int,
    zoom: int,
    fetch_index: Callable[[str], pa.Table] = fetch_stac_index,
):
    """Overture type -> its features in a map tile, or None if it has none there, read in parallel. `fetch_index()` gets Overture's index of its files (see `stac_index()`)."""
    bbox = tuple(mercantile.bounds(x, y, zoom))
    index = stac_index(release, fetch_index)
    roads = pc.field("class").isin(ROAD_CLASSES)
    tables = await asyncio.gather(
        *(
            asyncio.to_thread(
                _read,
                release,
                index,
                overture_type,
                bbox,
                columns,
                roads if overture_type == "segment" else None,
            )
            for overture_type, columns in COLUMNS.items()
        )
    )
    return dict(zip(COLUMNS, tables))
