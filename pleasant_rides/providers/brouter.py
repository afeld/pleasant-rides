import httpx

from ..models import Point
from .base import Provider

URL = "https://brouter.de/brouter"


class BRouter(Provider):
    name = "BRouter"

    # The public server's profiles are listed at https://brouter.de/brouter/profiles2/. "fastbike-lowtraffic" (see
    # https://brouter.de/brouter/profiles2/fastbike-lowtraffic.brf) penalizes roads that usually have traffic. On four
    # sample trips (long, urban, rural, suburban) it averaged 78.7 by our scores, vs. 73.9 for the previous default,
    # "trekking". "fastbike-verylowtraffic" (78.4), "racebike-verylowtraffic" (77.5), and "safety" (75.3) were close;
    # "gravel" scored well but kept failing on the long trip.
    def __init__(self, profile: str = "fastbike-lowtraffic"):
        self.profile = profile

    async def fetch(self, origin: Point, destination: Point):
        # https://github.com/abrensch/brouter/blob/master/docs/developers/http_server.md
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
        if response.is_error:
            # the body says what went wrong, e.g. that the public server gave up on a long route while busy
            # ("operation killed by thread-priority-watchdog"), which tends to work on a retry
            raise RuntimeError(
                f"BRouter {response.status_code}: {response.text.strip()}"
            )
        feature = response.json()["features"][0]
        # GeoJSON coordinates are [lon, lat(, elevation)]
        points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
        return [(f"BRouter ({self.profile})", points)]
