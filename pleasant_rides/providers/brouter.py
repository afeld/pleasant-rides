import hashlib
from pathlib import Path

import httpx

from .. import http_client
from ..models import Point
from ..politeness import ProviderError
from .base import Provider

URL = "https://brouter.de/brouter"

# our own profile, which gets uploaded to the server for each request
PLEASANT_PROFILE = Path(__file__).with_name("pleasant.brf")


class BRouter(Provider):
    name = "BRouter"
    # a free public server
    request_interval_s = 2

    # `profile` is one of the public server's profiles, listed at https://brouter.de/brouter/profiles2/, or a local
    # .brf file. `params` overrides the profile's `assign` variables for a request, e.g. {"consider_traffic": 0.5}.
    #
    # pleasant.brf is "fastbike-lowtraffic" (https://brouter.de/brouter/profiles2/fastbike-lowtraffic.brf) plus
    # penalties for fast and wide roads, climbs, and primary/secondary/tertiary roads. On the Benchmark page's sample
    # trips it averaged 81.8, vs. 78.7 for "fastbike-lowtraffic", though its long trip is ~11% longer; the variants in
    # benchmark/variants.py are the alternatives tried.
    def __init__(
        self, profile: str | Path = PLEASANT_PROFILE, params: dict | None = None
    ):
        self.profile = profile
        self.params = params or {}

    @property
    def cache_key(self):
        key = super().cache_key
        if isinstance(self.profile, Path):
            # so that editing the file gets new routes
            key += hashlib.sha256(self.profile.read_bytes()).hexdigest()
        return key

    async def _profile_id(self, client: httpx.AsyncClient):
        if not isinstance(self.profile, Path):
            return self.profile
        response = await client.post(
            f"{URL}/profile", content=self.profile.read_text(), timeout=30.0
        )
        body = response.json()
        if response.is_error or "error" in body:
            raise ProviderError(f"BRouter profile upload: {body.get('error')}")
        return body["profileid"]

    @property
    def profile_name(self):
        return self.profile.stem if isinstance(self.profile, Path) else self.profile

    async def fetch(self, origin: Point, destination: Point):
        # https://github.com/abrensch/brouter/blob/master/docs/developers/http_server.md
        async with http_client.client() as client:
            response = await client.get(
                URL,
                params={
                    "lonlats": f"{origin.lon},{origin.lat}|{destination.lon},{destination.lat}",
                    "profile": await self._profile_id(client),
                    "alternativeidx": 0,
                    "format": "geojson",
                    # the server rejects "true"/"false"
                    **{
                        f"profile:{k}": int(v) if isinstance(v, bool) else v
                        for k, v in self.params.items()
                    },
                },
                timeout=120.0,
            )
        if response.is_error:
            # the body says what went wrong: e.g. that the public server gave up on a long route while busy
            # ("operation killed by thread-priority-watchdog"), which tends to work on a retry, or to slow down
            # (403 "Please, retry later!")
            text = response.text.strip()
            raise ProviderError(
                f"BRouter {response.status_code}: {text}",
                retryable=response.status_code >= 500 or "watchdog" in text,
                rate_limited=response.status_code in (403, 429),
            )
        feature = response.json()["features"][0]
        # GeoJSON coordinates are [lon, lat(, elevation)]
        points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
        return [(f"BRouter ({self.profile_name})", points)]
