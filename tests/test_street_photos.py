import asyncio

import mapbox_vector_tile
import mercantile
import pandas as pd
import pytest
import shapely

from pleasant_rides import street_photos as sp
from pleasant_rides.models import Point

# heading north up a street in Manhattan, ~220 m
ROUTE = (Point(40.7580, -73.9850), Point(40.7600, -73.9850))


def photo(id: str, lat: float, lon: float, angle: float, pano=False, captured_at=0):
    return {
        "id": id,
        "lat": lat,
        "lon": lon,
        "compass_angle": angle,
        "is_pano": pano,
        "captured_at": captured_at,
    }


def steps(*photos: dict):
    return sp.steps_along(ROUTE, pd.DataFrame(list(photos)))


def test_parse_tile():
    tile = mercantile.tile(-73.985, 40.759, sp.ZOOM)
    content = mapbox_vector_tile.encode(
        {
            "name": "image",
            "features": [
                {
                    "geometry": shapely.Point(-73.985, 40.759),
                    "properties": {
                        "id": 123,
                        "compass_angle": 10.5,
                        "is_pano": True,
                        "captured_at": 1_700_000_000_000,
                    },
                }
            ],
        },
        default_options={"quantize_bounds": mercantile.bounds(tile)},
    )
    photos = sp.parse_tile(content, tile.x, tile.y)
    [row] = photos.to_dict("records")
    assert row["id"] == "123"
    assert row["lat"] == pytest.approx(40.759, abs=1e-5)
    assert row["lon"] == pytest.approx(-73.985, abs=1e-5)
    assert (row["compass_angle"], row["is_pano"]) == (10.5, True)


def test_parse_tile_without_photos():
    tile = mercantile.tile(-73.985, 40.759, sp.ZOOM)
    assert sp.parse_tile(b"", tile.x, tile.y).empty


def test_steps_follow_the_route():
    result = steps(
        photo("start", 40.7580, -73.9850, 0),
        photo("middle", 40.7590, -73.9850, 5),
        photo("end", 40.7600, -73.9850, 355),
    )
    assert [s.photo_id for s in result] == ["start", "middle", "end"]
    assert [round(s.along_m, -1) for s in result] == [0, 110, 220]
    # north, which can also come out as just under 360
    assert all(min(s.bearing, 360 - s.bearing) < 1 for s in result)


def test_steps_skip_photos_facing_the_other_way_unless_360():
    result = steps(
        photo("backward", 40.7580, -73.9850, 180),
        photo("pano", 40.7590, -73.9850, 180, pano=True),
    )
    assert [s.photo_id for s in result] == ["pano"]


def test_steps_skip_photos_off_the_route():
    # ~85 m east
    assert steps(photo("far", 40.7590, -73.9840, 0)) == []


def test_steps_prefer_newer_photos_about_as_close():
    result = steps(
        photo("old", 40.7590, -73.9850, 0, captured_at=1),
        photo("new", 40.75901, -73.98501, 0, captured_at=2),
    )
    assert [s.photo_id for s in result] == ["new"]


def test_route_steps_fetches_each_tile_once():
    fetched = []

    async def fetch_tile(x: int, y: int):
        fetched.append((x, y))
        return pd.DataFrame([photo("only", 40.7590, -73.9850, 0)])

    result = asyncio.run(sp.route_steps(ROUTE, fetch_tile))
    assert len(fetched) == len(set(fetched)) >= 1
    assert [s.photo_id for s in result] == ["only"]


def test_route_steps_fetches_a_few_tiles_at_a_time():
    # ~10 km north, across several tiles
    route = (Point(40.70, -73.99), Point(40.79, -73.99))
    active, most = 0, 0

    async def fetch_tile(x: int, y: int):
        nonlocal active, most
        active += 1
        most = max(most, active)
        await asyncio.sleep(0.01)
        active -= 1
        return pd.DataFrame(columns=sp.COLUMNS)

    asyncio.run(sp.route_steps(route, fetch_tile))
    assert most == sp.CONCURRENT_TILES
