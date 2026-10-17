import httpx

from ..models import Point
from .base import Provider

URL = "https://api.cyclemate.club/directions/v2/"


class Cyclemate(Provider):
    """Requires a key (request one via https://docs.cyclemate.club)."""

    name = "Cyclemate"
    api_key_var = "CYCLEMATE_API_KEY"

    async def fetch(self, origin: Point, destination: Point):
        api_key = self.api_key
        async with httpx.AsyncClient() as client:
            response = await client.post(
                URL,
                headers={"apikey": api_key},
                json={
                    "coordinates": [
                        [origin.lon, origin.lat],
                        [destination.lon, destination.lat],
                    ],
                    "profile": "cycling",
                    "supersafe": True,
                },
                timeout=60.0,
            )
        response.raise_for_status()
        route = response.json()["route"]
        if route is None:
            return []
        # GeoJSON coordinates are [lon, lat]
        points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
        return [("SuperSafe", points)]
