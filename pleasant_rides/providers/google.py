from typing import Any

import httpx
import polyline

from ..models import Point
from .base import Provider

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#routelabel
ROUTE_LABELS = {"DEFAULT_ROUTE": "Best route", "DEFAULT_ROUTE_ALTERNATE": "Alternate"}


class Google(Provider):
    """Requires a key with the Routes API enabled."""

    name = "Google Maps"
    api_key_var = "GOOGLE_MAPS_API_KEY"

    async def fetch(self, origin: Point, destination: Point):
        api_key = self.api_key

        def waypoint(p: Point):
            return {"location": {"latLng": {"latitude": p.lat, "longitude": p.lon}}}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                URL,
                headers={
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": "routes.polyline.encodedPolyline,routes.routeLabels,routes.description",
                },
                json={
                    "origin": waypoint(origin),
                    "destination": waypoint(destination),
                    "travelMode": "BICYCLE",
                    "computeAlternativeRoutes": True,
                },
                timeout=60.0,
            )
        response.raise_for_status()
        routes = response.json().get("routes", [])
        return [
            (_label(r), polyline.decode(r["polyline"]["encodedPolyline"]))
            for r in routes
        ]


def _label(route: dict[str, Any]):
    """e.g. "Best route via Empire State Trl", from Google's label and its summary of the main road taken."""
    kinds = [ROUTE_LABELS[k] for k in route.get("routeLabels", []) if k in ROUTE_LABELS]
    label = kinds[0] if kinds else "Route"
    if route.get("description"):
        label += f" via {route['description']}"
    return label
