from . import http_client
from .models import Point


def geocode_place(query: str):
    response = http_client.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
        timeout=30.0,
    )
    result = response.json()[0]
    return Point(float(result["lat"]), float(result["lon"]))
