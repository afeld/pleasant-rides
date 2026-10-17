import httpx

from ..models import Point
from .base import Provider

URL = "https://graphhopper.com/api/1/route"

# https://docs.graphhopper.com/openapi/custom-model
# `priority` adjusts how much a road is preferred (0 = never use); `speed` affects travel time.
PLEASANT_MODEL = {
    "priority": [
        {"if": "road_class == MOTORWAY || road_class == TRUNK", "multiply_by": "0"},
        {"else_if": "road_class == PRIMARY", "multiply_by": "0.3"},
        {"else_if": "road_class == SECONDARY", "multiply_by": "0.6"},
        {"if": "max_speed > 50", "multiply_by": "0.5"},
        {"if": "road_class == CYCLEWAY || bike_network != MISSING", "multiply_by": "1.5"},
        {"if": "surface == GRAVEL || surface == DIRT || surface == SAND", "multiply_by": "0.5"},
    ],
    "speed": [
        # slow down steep climbs so they cost more time
        {"if": "average_slope > 6", "multiply_by": "0.6"},
    ],
}


class GraphHopper(Provider):
    """Requires a key (sign up at https://www.graphhopper.com).

    `custom_model=True` applies PLEASANT_MODEL, which needs a paid plan ("flexible mode").
    """

    name = "GraphHopper"
    api_key_var = "GRAPHHOPPER_API_KEY"

    def __init__(self, profile: str = "bike", custom_model: bool = False):
        self.profile = profile
        self.custom_model = custom_model

    async def fetch(self, origin: Point, destination: Point):
        api_key = self.api_key
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
        async with httpx.AsyncClient() as client:
            response = await client.post(URL, params={"key": api_key}, json=body, timeout=60.0)
        if response.is_error:
            # the status alone doesn't say what was wrong with the request
            raise RuntimeError(f"GraphHopper {response.status_code}: {response.json().get('message')}")
        paths = response.json()["paths"]
        # GeoJSON coordinates are [lon, lat]
        return [
            (f"GraphHopper {i}", [(c[1], c[0]) for c in path["points"]["coordinates"]])
            for i, path in enumerate(paths, start=1)
        ]
