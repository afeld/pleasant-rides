from pathlib import Path

import httpx

from ..models import Point
from .base import Provider

URL = "https://brouter.de/brouter"

# our own profile, which gets uploaded to the server for each request
PLEASANT_PROFILE = Path(__file__).with_name("pleasant.brf")


class BRouter(Provider):
    name = "BRouter"

    # `profile` is one of the public server's profiles, listed at https://brouter.de/brouter/profiles2/, or a local
    # .brf file. Average scores on four sample trips (long, urban, rural, suburban):
    #
    # - pleasant.brf: 81.8, though its long trip is ~11% longer than with "fastbike-lowtraffic". It's
    #   "fastbike-lowtraffic" plus penalties for fast and wide roads, climbs, and primary/secondary/tertiary roads.
    #   Doubling those penalties only reached 82.0, with the long trip another ~4% longer, and preferring forests and
    #   rivers didn't help.
    # - "fastbike-lowtraffic" (https://brouter.de/brouter/profiles2/fastbike-lowtraffic.brf): 78.7, penalizing roads
    #   that usually have traffic. "fastbike-verylowtraffic" (78.4), "racebike-verylowtraffic" (77.5), "safety"
    #   (75.3), and "trekking" (73.9) did worse; "gravel" scored well but kept failing on the long trip.
    # - "quaelnix-gravel", with its traffic, cycle route, and steep incline switches on: 81.4, with a long trip ~16%
    #   longer than with "fastbike-lowtraffic".
    def __init__(self, profile: str | Path = PLEASANT_PROFILE):
        self.profile = profile

    async def _profile_id(self, client: httpx.AsyncClient):
        if not isinstance(self.profile, Path):
            return self.profile
        response = await client.post(
            f"{URL}/profile", content=self.profile.read_text(), timeout=30.0
        )
        body = response.json()
        if response.is_error or "error" in body:
            raise RuntimeError(f"BRouter profile upload: {body.get('error')}")
        return body["profileid"]

    @property
    def profile_name(self):
        return self.profile.stem if isinstance(self.profile, Path) else self.profile

    async def fetch(self, origin: Point, destination: Point):
        # https://github.com/abrensch/brouter/blob/master/docs/developers/http_server.md
        async with httpx.AsyncClient() as client:
            response = await client.get(
                URL,
                params={
                    "lonlats": f"{origin.lon},{origin.lat}|{destination.lon},{destination.lat}",
                    "profile": await self._profile_id(client),
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
        return [(f"BRouter ({self.profile_name})", points)]
