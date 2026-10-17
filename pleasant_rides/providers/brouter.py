import httpx

from ..models import Point
from .base import Provider

URL = "https://brouter.de/brouter"


class BRouter(Provider):
    name = "BRouter"

    def __init__(self, profile: str = "trekking"):
        self.profile = profile

    async def fetch(self, origin: Point, destination: Point):
        # https://github.com/abrensch/brouter/blob/master/brouter-server/src/main/resources/readme.md
        async with httpx.AsyncClient() as client:
            response = await client.get(
                URL,
                params={
                    "lonlats": f"{origin.lon},{origin.lat}|{destination.lon},{destination.lat}",
                    "profile": self.profile,
                    "alternativeidx": 0,
                    "format": "geojson",
                },
                timeout=120.0,
            )
        response.raise_for_status()
        feature = response.json()["features"][0]
        # GeoJSON coordinates are [lon, lat(, elevation)]
        points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
        return [(f"BRouter ({self.profile})", points)]
