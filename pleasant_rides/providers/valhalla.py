import json
from typing import Any

import httpx
import polyline

from ..models import Point
from .base import Provider

URL = "https://valhalla1.openstreetmap.de/route"


def _decode_trip(trip: dict[str, Any]):
    points: list[tuple[float, float]] = []
    for leg in trip["legs"]:
        leg_points = polyline.decode(leg["shape"], precision=6)
        if points and leg_points and points[-1] == leg_points[0]:
            leg_points = leg_points[1:]
        points.extend(leg_points)
    return points


# https://valhalla.github.io/valhalla/api/route/api-reference/#bicycle-costing-options
# On the sample trips in benchmark.py these averaged 79.9, vs. 78.6 with the previous settings (bicycle_type "road",
# use_roads 0.2, avoid_bad_surfaces 0.8); the variants there are the alternatives tried.
PLEASANT_OPTIONS = {
    # assumes wider tires than "road", so crushed gravel and the like aren't avoided as much
    "bicycle_type": "hybrid",
    # 0 avoids roads (as opposed to bike paths) as much as possible
    "use_roads": 0.0,
    "use_hills": 0.3,
    "use_ferry": 0.0,
    # our "smooth" metric only counts dirt, gravel, and worse as rough
    "avoid_bad_surfaces": 0.5,
}


class Valhalla(Provider):
    name = "Valhalla"

    def __init__(self, costing_options: dict = PLEASANT_OPTIONS):
        self.costing_options = costing_options

    async def fetch(self, origin: Point, destination: Point):
        params = {
            "locations": [
                {"lat": origin.lat, "lon": origin.lon},
                {"lat": destination.lat, "lon": destination.lon},
            ],
            "costing": "bicycle",
            "costing_options": {"bicycle": self.costing_options},
            "directions_options": {"units": "miles"},
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(
                URL,
                params={"json": json.dumps(params, separators=(",", ":"))},
                timeout=60.0,
            )
        response.raise_for_status()
        payload = response.json()

        trips = [("Primary", payload["trip"])]
        for i, alt in enumerate(payload.get("alternates", []), start=1):
            trips.append((f"Alternate {i}", alt.get("trip", alt)))
        return [(label, _decode_trip(trip)) for label, trip in trips]
