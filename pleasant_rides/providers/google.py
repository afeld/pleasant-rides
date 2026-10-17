import os

import httpx
import polyline

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def get_routes(origin, destination):
    """Requires GOOGLE_MAPS_API_KEY with the Routes API enabled."""
    api_key = os.environ["GOOGLE_MAPS_API_KEY"]

    def waypoint(p):
        return {"location": {"latLng": {"latitude": p["lat"], "longitude": p["lon"]}}}

    response = httpx.post(
        URL,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.polyline.encodedPolyline",
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
        (f"Google {i}", polyline.decode(r["polyline"]["encodedPolyline"]))
        for i, r in enumerate(routes, start=1)
    ]
