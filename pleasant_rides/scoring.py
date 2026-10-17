"""Scores routes against the README's working definition of "pleasant", using road attributes from OpenStreetMap.

Each route is map-matched with Valhalla's `trace_attributes`, which returns the edges (road segments) it follows.
Most metrics are the share of the route's distance that meets a condition. Not covered yet: scenery, points of
interest, and remoteness.
"""

import httpx

URL = "https://valhalla1.openstreetmap.de/trace_attributes"

ATTRIBUTES = [
    "edge.length",
    "edge.road_class",
    "edge.use",
    "edge.cycle_lane",
    "edge.bicycle_network",
    "edge.speed_limit",
    "edge.lane_count",
    "edge.surface",
    "edge.mean_elevation",
    "edge.max_upward_grade",
]

# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
BUSY_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary"}
CAR_FREE_USES = {"cycleway", "path", "footway", "pedestrian", "mountain_bike", "living_street", "track"}
SEPARATED_CYCLE_LANES = {"dedicated", "separated"}
ROUGH_SURFACES = {"paved_rough", "compacted", "dirt", "gravel", "path", "impassable"}

FAST_KPH = 50  # ~30 mph
STEEP_GRADE = 6  # percent

# how much each metric counts toward the overall score; higher shares are better for each
WEIGHTS = {
    "low_traffic": 3,
    "slow": 2,
    "few_lanes": 1,
    "smooth": 1,
    "gentle": 2,
}


async def get_edges(points):
    """Map-matches `points` [(lat, lon), ...] to the road network, returning Valhalla's edges."""
    body = {
        "shape": [{"lat": lat, "lon": lon} for lat, lon in points],
        "costing": "bicycle",
        "shape_match": "map_snap",
        "filters": {"attributes": ATTRIBUTES, "action": "include"},
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(URL, json=body, timeout=120.0)
    if response.is_error:
        raise RuntimeError(f"Valhalla {response.status_code}: {response.json().get('error')}")
    return response.json()["edges"]


def _share(edges, condition):
    total = sum(e["length"] for e in edges)
    return sum(e["length"] for e in edges if condition(e)) / total if total else None


def _is_low_traffic(edge):
    return (
        edge.get("use") in CAR_FREE_USES
        or edge.get("cycle_lane") in SEPARATED_CYCLE_LANES
        or edge.get("road_class") not in BUSY_ROAD_CLASSES
    )


def _climb(edges):
    """Total elevation gain in meters, from the change in mean elevation between consecutive edges."""
    elevations = [e["mean_elevation"] for e in edges if e.get("mean_elevation") is not None]
    return sum(max(b - a, 0) for a, b in zip(elevations, elevations[1:]))


def score(edges):
    """Returns metrics for a map-matched route, each a share of its distance (0-1), plus an overall 0-100 score."""
    # only roads have speed limits and lanes; unknown speed limits are left out rather than guessed
    roads = [e for e in edges if e.get("use") not in CAR_FREE_USES]
    posted = [e for e in roads if e.get("speed_limit")]
    metrics = {
        "distance_km": sum(e["length"] for e in edges),
        "low_traffic": _share(edges, _is_low_traffic),
        "slow": _share(posted, lambda e: e["speed_limit"] < FAST_KPH) if posted else None,
        "few_lanes": _share(roads, lambda e: e.get("lane_count", 1) <= 2) if roads else 1.0,
        "smooth": _share(edges, lambda e: e.get("surface") not in ROUGH_SURFACES),
        "gentle": _share(edges, lambda e: e.get("max_upward_grade", 0) < STEEP_GRADE),
        "bike_network": _share(edges, lambda e: bool(e.get("bicycle_network"))),
        "climb_m": _climb(edges),
    }
    scored = {k: w for k, w in WEIGHTS.items() if metrics[k] is not None}
    metrics["score"] = 100 * sum(metrics[k] * w for k, w in scored.items()) / sum(scored.values())
    return metrics


async def score_route(points):
    return score(await get_edges(points))
