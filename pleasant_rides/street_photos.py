"""Mapillary's street-level photos along a route, so the app can show what its roads and paths look like, one step at a time.

The photos' positions and directions come from Mapillary's coverage tiles (https://www.mapillary.com/developer/api-documentation#coverage-tiles), which list every photo in a ~2.4 km square, so a whole route takes one request per tile rather than one per photo. The browser then loads the photos themselves from Mapillary, with MapillaryJS (see `map.RoutePreview`).
"""

import asyncio
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import mapbox_vector_tile
import mercantile
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

from . import http_client
from .models import Point
from .politeness import status_error, wait_turn
from .providers.base import MissingAPIKey

TOKEN_VAR = "MAPILLARY_ACCESS_TOKEN"
SERVER = "tiles.mapillary.com"
# Mapillary allows 50,000 tile requests a day; a route takes a few dozen at most, which are cached. A few at a time, since each is a download of up to a few MB: one at a time, a 10 mile route's 8 tiles took ~7 s.
REQUEST_INTERVAL_S = 0.2
CONCURRENT_TILES = 3
# the zoom level whose coverage tiles list individual photos
ZOOM = 14

# how far apart the steps along the route are, how far from the route a photo can be, and how far off the route's direction a photo (other than a 360° one) can face
STEP_M = 50
NEAR_M = 20
FACING_DEGREES = 60
# photos about this close to a step are treated as equally close, so the newest of them wins
CLOSE_ENOUGH_M = 5

COLUMNS = ["id", "lat", "lon", "compass_angle", "is_pano", "captured_at"]


def token():
    """The access token for Mapillary's API, which the browser also uses to load the photos."""
    value = os.environ.get(TOKEN_VAR)
    if not value:
        raise MissingAPIKey(f"set {TOKEN_VAR}")
    return value


async def fetch_tile(x: int, y: int):
    """The photos in a coverage tile, as a DataFrame with COLUMNS."""
    await wait_turn(SERVER, REQUEST_INTERVAL_S)
    async with http_client.client() as client:
        response = await client.get(
            f"https://{SERVER}/maps/vtp/mly1_public/2/{ZOOM}/{x}/{y}",
            params={"access_token": token()},
            timeout=60.0,
        )
    if response.is_error:
        raise status_error("Mapillary", response, response.text)
    # in a thread, so other tiles download meanwhile
    return await asyncio.to_thread(parse_tile, response.content, x, y)


def parse_tile(content: bytes, x: int, y: int):
    layer = mapbox_vector_tile.decode(content).get("image") if content else None
    if not layer:
        return pd.DataFrame(columns=COLUMNS)
    # coordinates are in the tile's own grid, from its southwest corner; Web Mercator is linear across it
    left, bottom, right, top = mercantile.xy_bounds(x, y, ZOOM)
    extent = layer["extent"]
    rows = []
    for feature in layer["features"]:
        px, py = feature["geometry"]["coordinates"]
        lon, lat = mercantile.lnglat(
            left + (right - left) * px / extent, bottom + (top - bottom) * py / extent
        )
        props = feature["properties"]
        rows.append(
            (
                str(props["id"]),
                lat,
                lon,
                props.get("compass_angle", 0.0),
                bool(props.get("is_pano")),
                props.get("captured_at", 0),
            )
        )
    return pd.DataFrame(rows, columns=COLUMNS)


@dataclass(frozen=True)
class Step:
    """A photo to show at a point along the route."""

    photo_id: str
    # the photo's position, which is near the route but not on it
    point: Point
    # how far along the route it is
    along_m: float
    # the route's direction there, in degrees clockwise from north
    bearing: float
    is_pano: bool
    # which way the camera faced, in degrees clockwise from north
    compass_angle: float


async def route_steps(
    points: Sequence[Point],
    fetch_tile: Callable[[int, int], Awaitable[pd.DataFrame]] = fetch_tile,
):
    """The steps along the route that have a photo, in order. `fetch_tile()` gets a coverage tile's photos (see `fetch_tile()`); CONCURRENT_TILES are fetched at a time."""
    tiles = sorted({(t.x, t.y) for t in map(_tile, _samples(points)[0])})
    limit = asyncio.Semaphore(CONCURRENT_TILES)

    async def fetch(x: int, y: int):
        async with limit:
            return await fetch_tile(x, y)

    frames = await asyncio.gather(*(fetch(x, y) for x, y in tiles))
    photos = pd.concat(
        [f for f in frames if not f.empty] or [pd.DataFrame(columns=COLUMNS)]
    )
    return steps_along(points, photos)


def _tile(point: Point):
    return mercantile.tile(point.lon, point.lat, ZOOM)


def _projection(points: Sequence[Point]):
    """To and from meters around the route, which are accurate enough for distances of tens of meters."""
    lat0 = sum(p.lat for p in points) / len(points)
    lon0 = sum(p.lon for p in points) / len(points)
    crs = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +units=m"
    return (
        Transformer.from_crs("EPSG:4326", crs, always_xy=True),
        Transformer.from_crs(crs, "EPSG:4326", always_xy=True),
    )


def _samples(points: Sequence[Point]):
    """Points every STEP_M along the route and its bearing at each, plus the route and those points in meters, and the projection to meters."""
    to_m, from_m = _projection(points)
    xs, ys = to_m.transform([p.lon for p in points], [p.lat for p in points])
    line = shapely.LineString(list(zip(xs, ys)))
    # including the end, so the last stretch isn't skipped
    along = np.append(np.arange(0, line.length, STEP_M), line.length)
    here = shapely.line_interpolate_point(line, along)
    # the bearing from a bit behind to a bit ahead, so it works at both ends
    behind = shapely.line_interpolate_point(line, (along - 5).clip(min=0))
    ahead = shapely.line_interpolate_point(line, (along + 5).clip(max=line.length))
    dx = shapely.get_x(ahead) - shapely.get_x(behind)
    dy = shapely.get_y(ahead) - shapely.get_y(behind)
    bearings = np.degrees(np.arctan2(dx, dy)) % 360
    lons, lats = from_m.transform(shapely.get_x(here), shapely.get_y(here))
    samples = [Point(lat, lon) for lat, lon in zip(lats, lons)]
    return samples, line, bearings, here, to_m


def steps_along(points: Sequence[Point], photos: pd.DataFrame):
    """For each point every STEP_M along the route, the nearest photo within NEAR_M that faces along it (or is 360°), preferring newer ones; consecutive repeats are dropped."""
    if photos.empty or len(points) < 2:
        return []
    _, line, bearings, here, to_m = _samples(points)
    xs, ys = to_m.transform(photos["lon"].to_numpy(), photos["lat"].to_numpy())
    photo_points = shapely.points(xs, ys)
    sample_idx, photo_idx = shapely.STRtree(photo_points).query(
        here, predicate="dwithin", distance=NEAR_M
    )
    if not len(sample_idx):
        return []
    angles = photos["compass_angle"].to_numpy(dtype=float)
    panos = photos["is_pano"].to_numpy(dtype=bool)
    off = np.abs((angles[photo_idx] - bearings[sample_idx] + 180) % 360 - 180)
    ok = panos[photo_idx] | (off <= FACING_DEGREES)
    sample_idx, photo_idx = sample_idx[ok], photo_idx[ok]
    distance = shapely.distance(here[sample_idx], photo_points[photo_idx])
    captured = photos["captured_at"].to_numpy(dtype=float)[photo_idx]
    # by sample, then closeness, then newest first
    order = np.lexsort((-captured, np.floor(distance / CLOSE_ENOUGH_M), sample_idx))
    steps: list[Step] = []
    seen_samples = set()
    for k in order:
        i, j = int(sample_idx[k]), int(photo_idx[k])
        if i in seen_samples:
            continue
        seen_samples.add(i)
        row = photos.iloc[j]
        if steps and steps[-1].photo_id == row["id"]:
            continue
        steps.append(
            Step(
                photo_id=row["id"],
                point=Point(float(row["lat"]), float(row["lon"])),
                along_m=float(line.project(photo_points[j])),
                bearing=float(bearings[i]),
                is_pano=bool(row["is_pano"]),
                compass_angle=float(row["compass_angle"]),
            )
        )
    return steps
