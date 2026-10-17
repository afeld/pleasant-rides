"""Map-matches routes to OpenStreetMap's roads with Valhalla's `trace_attributes`, which returns the edges (road
segments) a route follows, with their attributes, and the intersections between them."""

from collections.abc import Sequence
from typing import Any

from . import http_client
from .models import Point
from .politeness import status_error, wait_turn
from .providers import valhalla

# a road segment from Valhalla's trace_attributes
Edge = dict[str, Any]

URL = f"https://{valhalla.SERVER}/trace_attributes"

# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
ATTRIBUTES = [
    "edge.length",
    "edge.road_class",
    "edge.use",
    "edge.cycle_lane",
    "edge.bicycle_network",
    "edge.speed_limit",
    "edge.lane_count",
    "edge.surface",
    "edge.sac_scale",
    "edge.mean_elevation",
    "edge.max_upward_grade",
    "edge.begin_heading",
    "edge.end_heading",
    "edge.internal_intersection",
    "edge.roundabout",
    "edge.forward",
    "edge.traversability",
    "node.intersecting_edge.use",
    "node.intersecting_edge.driveability",
]


async def get_edges(points: Sequence[Point]):
    """Map-matches `points` [(lat, lon), ...] to the road network, returning Valhalla's edges."""
    body = {
        "shape": [{"lat": lat, "lon": lon} for lat, lon in points],
        "costing": "bicycle",
        "shape_match": "map_snap",
        "filters": {"attributes": ATTRIBUTES, "action": "include"},
    }
    await wait_turn(valhalla.SERVER, valhalla.REQUEST_INTERVAL_S)
    async with http_client.client() as client:
        response = await client.post(URL, json=body, timeout=120.0)
    if response.is_error:
        raise status_error("Valhalla", response, response.json().get("error"))
    return response.json()["edges"]
