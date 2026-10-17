import httpx

from .models import Point


def geocode_place(query):
    response = httpx.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": "pleasant-rides/1.0"},
        timeout=30.0,
    )
    result = response.json()[0]
    return Point(float(result["lat"]), float(result["lon"]))
