import hashlib
from pathlib import Path

import httpx

from .. import http_client
from ..models import Point
from ..politeness import ProviderError
from .base import Provider

URL = "https://brouter.de/brouter"

# what the app uses: quaelnix-gravel (https://brouter.de/brouter/profiles2/quaelnix-gravel.brf), with its switches for considering traffic, preferring cycle routes, and avoiding steep inclines on. On the Benchmark page's sample trips it averaged 79.0, vs. 78.2 for pleasant.brf, though its long trip is ~4% longer than pleasant.brf's. Also turning on its preference for quiet areas (78.7), rivers (78.4), forests (76.3), or both (76.3) scored lower, as did adding a forest preference to pleasant.brf (76.5); the variants in benchmark/variants.py are the alternatives tried.
DEFAULT_PROFILE = "quaelnix-gravel"
DEFAULT_PARAMS = {
    "consider_traffic_estimate": True,
    "prefer_cycle_routes": True,
    "avoid_steep_inclines": True,
}

# our own profile, which gets uploaded to the server: "fastbike-lowtraffic" (https://brouter.de/brouter/profiles2/fastbike-lowtraffic.brf) plus penalties for fast and wide roads, climbs, and primary/secondary/tertiary roads. It was the default before scenery, points of interest, and remoteness were scored.
PLEASANT_PROFILE = Path(__file__).with_name("pleasant.brf")

# quaelnix-gravel with the default parameters, avoiding noisy areas (roads close to busy ones), with `noise_strength` to scale how strongly; see the file
QUIET_PROFILE = Path(__file__).with_name("quiet.brf")

# a local profile's contents (as `_digest()`) -> the ID the server gave it when uploaded, so each version is only uploaded once. The server deletes uploaded profiles eventually (then answering with an empty 500), so an ID is forgotten whenever a request using it fails, and the profile gets uploaded again on the next try.
_uploaded: dict[str, str] = {}


def _digest(profile: Path):
    return hashlib.sha256(profile.read_bytes()).hexdigest()


class BRouter(Provider):
    name = "BRouter"
    # a free public server
    request_interval_s = 2

    # `profile` is one of the public server's profiles, listed at https://brouter.de/brouter/profiles2/, or a local .brf file. `params` overrides the profile's `assign` variables for a request, e.g. {"consider_traffic": 0.5}; without it, the default profile gets DEFAULT_PARAMS, and others none.
    def __init__(
        self, profile: str | Path = DEFAULT_PROFILE, params: dict | None = None
    ):
        self.profile = profile
        if params is None:
            params = DEFAULT_PARAMS if profile == DEFAULT_PROFILE else {}
        self.params = params

    @property
    def cache_key(self):
        key = super().cache_key
        if isinstance(self.profile, Path):
            # so that editing the file gets new routes
            key += _digest(self.profile)
        return key

    async def _profile_id(self, client: httpx.AsyncClient):
        if not isinstance(self.profile, Path):
            return self.profile
        digest = _digest(self.profile)
        if digest not in _uploaded:
            _uploaded[digest] = await _upload(client, self.profile)
        return _uploaded[digest]

    @property
    def profile_name(self):
        return self.profile.stem if isinstance(self.profile, Path) else self.profile

    def _overrides(self):
        """`params` as the server expects them."""
        # the server rejects "true"/"false"
        return {
            f"profile:{k}": int(v) if isinstance(v, bool) else v
            for k, v in self.params.items()
        }

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
                    **self._overrides(),
                },
                timeout=120.0,
            )
        if response.is_error:
            if isinstance(self.profile, Path):
                _uploaded.pop(_digest(self.profile), None)
            raise _error(response)
        feature = response.json()["features"][0]
        # GeoJSON coordinates are [lon, lat(, elevation)]
        points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
        return [(f"BRouter ({self.profile_name})", points)]


async def _upload(client: httpx.AsyncClient, profile: Path):
    """Returns the ID the server gives the profile."""
    response = await client.post(
        f"{URL}/profile", content=profile.read_text(), timeout=30.0
    )
    body = response.json()
    if response.is_error or "error" in body:
        raise ProviderError(f"BRouter profile upload: {body.get('error')}")
    return body["profileid"]


def _error(response: httpx.Response):
    # the body says what went wrong: e.g. that the public server gave up on a long route while busy
    # ("operation killed by thread-priority-watchdog"), which tends to work on a retry, or to slow down
    # (403 "Please, retry later!")
    text = response.text.strip()
    return ProviderError(
        f"BRouter {response.status_code}: {text}",
        retryable=response.status_code >= 500 or "watchdog" in text,
        rate_limited=response.status_code in (403, 429),
    )
