import json

import httpx
import polyline

from .base import Provider

URL = "https://valhalla1.openstreetmap.de/route"


def _decode_trip(trip):
    points = []
    for leg in trip["legs"]:
        leg_points = polyline.decode(leg["shape"], precision=6)
        if points and leg_points and points[-1] == leg_points[0]:
            leg_points = leg_points[1:]
        points.extend(leg_points)
    return points


class Valhalla(Provider):
    name = "Valhalla"

    async def fetch(self, origin, destination):
        params = {
            "locations": [
                {"lat": origin.lat, "lon": origin.lon},
                {"lat": destination.lat, "lon": destination.lon},
            ],
            "costing": "bicycle",
            "costing_options": {
                "bicycle": {
                    "bicycle_type": "road",
                    "use_roads": 0.2,
                    "use_hills": 0.3,
                    "use_ferry": 0.0,
                    "avoid_bad_surfaces": 0.8,
                }
            },
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
