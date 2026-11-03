import os

from .. import http_client
from ..models import Point
from ..politeness import TIMEOUT_S, status_error
from .base import Provider

PUBLIC_URL = "https://graphhopper.com/api/1"

# https://docs.graphhopper.com/openapi/custom-model
# `priority` adjusts how much a road is preferred (0 = never use); `speed` affects travel time.
PLEASANT_MODEL = {
    "priority": [
        {"if": "road_class == MOTORWAY || road_class == TRUNK", "multiply_by": "0"},
        {"else_if": "road_class == PRIMARY", "multiply_by": "0.3"},
        {"else_if": "road_class == SECONDARY", "multiply_by": "0.6"},
        {"if": "max_speed > 50", "multiply_by": "0.5"},
        # prefer cycleways and bike routes 1.5x, by making everything else less preferred, since a model's priority can't go above 1
        {
            "if": "road_class != CYCLEWAY && bike_network == MISSING",
            "multiply_by": "0.67",
        },
        {
            "if": "surface == GRAVEL || surface == DIRT || surface == SAND",
            "multiply_by": "0.5",
        },
    ],
    "speed": [
        # slow down steep climbs so they cost more time
        {"if": "average_slope > 6", "multiply_by": "0.6"},
    ],
}


class GraphHopper(Provider):
    """Requires a key (sign up at https://www.graphhopper.com), unless GRAPHHOPPER_URL points at our own server (see graphhopper/Dockerfile).

    `custom_model=True` applies PLEASANT_MODEL, which on the hosted API needs a paid plan ("flexible mode"). The hosted free plan also only allows the "bike" profile among cycling ones, not "racingbike" or "mtb" (see https://docs.graphhopper.com/openapi/map-data-and-routing-profiles); our own server only has "bike" (see graphhopper/config.yml).
    """

    name = "GraphHopper"

    def __init__(self, profile: str = "bike", custom_model: bool = False):
        self.profile = profile
        self.custom_model = custom_model

    @property
    def url(self):
        """GRAPHHOPPER_URL points at another server, e.g. a local one (see compose.yaml).

        It's read when used rather than stored, so that it's only in the cache key for our own server, keeping the hosted API's cached routes.
        """
        return os.environ.get("GRAPHHOPPER_URL") or PUBLIC_URL

    @property
    def self_hosted(self):
        return self.url != PUBLIC_URL

    @property
    def api_key_var(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        return None if self.self_hosted else "GRAPHHOPPER_API_KEY"

    @property
    def request_interval_s(self):  # pyright: ignore[reportIncompatibleVariableOverride]
        # the hosted free plan is rate limited
        return 0 if self.self_hosted else 1

    @property
    def cache_key(self):
        key = super().cache_key
        # since servers' data differs
        return f"{key}@{self.url}" if self.self_hosted else key

    async def fetch(self, origin: Point, destination: Point):
        # our own server doesn't take a key
        params = {} if self.self_hosted else {"key": self.api_key}
        body = {
            "points": [
                [origin.lon, origin.lat],
                [destination.lon, destination.lat],
            ],
            "profile": self.profile,
            "algorithm": "alternative_route",
            "alternative_route.max_paths": 3,
            "points_encoded": False,
            "instructions": False,
        }
        if self.custom_model:
            body["custom_model"] = PLEASANT_MODEL
            body["ch.disable"] = True
        async with http_client.client() as client:
            response = await client.post(
                f"{self.url}/route", params=params, json=body, timeout=TIMEOUT_S
            )
        if response.is_error:
            # the status alone doesn't say what was wrong with the request
            raise status_error("GraphHopper", response, response.json().get("message"))
        paths = response.json()["paths"]
        # GeoJSON coordinates are [lon, lat]
        return [
            (f"GraphHopper {i}", [(c[1], c[0]) for c in path["points"]["coordinates"]])
            for i, path in enumerate(paths, start=1)
        ]
