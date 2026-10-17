import os

import httpx
import polyline

from ._labels import unique

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes#routelabel
ROUTE_LABELS = {"DEFAULT_ROUTE": "Best route", "DEFAULT_ROUTE_ALTERNATE": "Alternate"}


async def get_routes(origin, destination):
    """Requires GOOGLE_MAPS_API_KEY with the Routes API enabled."""
    api_key = os.environ["GOOGLE_MAPS_API_KEY"]

    def waypoint(p):
        return {"location": {"latLng": {"latitude": p["lat"], "longitude": p["lon"]}}}

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
    labels = unique(_label(r) for r in routes)
    return [(label, polyline.decode(r["polyline"]["encodedPolyline"])) for label, r in zip(labels, routes)]


def _label(route):
    """e.g. "Best route via Empire State Trl", from Google's label and its summary of the main road taken."""
    kinds = [ROUTE_LABELS[k] for k in route.get("routeLabels", []) if k in ROUTE_LABELS]
    label = kinds[0] if kinds else "Route"
    if route.get("description"):
        label += f" via {route['description']}"
    return label
