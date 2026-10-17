"""Scores routes against the README's working definition of "pleasant", using road attributes from OpenStreetMap.

Each route is map-matched with Valhalla's `trace_attributes`, which returns the edges (road segments) it follows and
the intersections between them. Most metrics are the share of the route's distance that meets a condition; turns and
intersections are counted per km. Not covered yet: scenery, points of interest, and remoteness.
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

# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
BUSY_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary"}
CAR_FREE_USES = {"cycleway", "path", "footway", "pedestrian", "mountain_bike", "living_street", "track", "steps"}
SEPARATED_CYCLE_LANES = {"dedicated", "separated"}
# pavement, boardwalks, and crushed gravel (OSM's "compacted"/"fine_gravel") are all fine
ROUGH_SURFACES = {"dirt", "gravel", "path", "impassable"}
# where you'd usually have to get off and walk
WALKING_USES = {"steps", "footway", "pedestrian", "sidewalk"}

FAST_KPH = 50  # ~30 mph
STEEP_GRADE = 6  # percent
TURN_DEGREES = 45  # a smaller change in heading between road segments is just a bend
# for metrics counted per km, the rate that scores 0.5; fewer is better
HALF_SCORE_TURNS_PER_KM = 1
HALF_SCORE_INTERSECTIONS_PER_KM = 3

# how much each metric counts toward the overall score, grouped as in the README; higher is better for each
WEIGHTS = {
    # easy
    "gentle": 2,
    "few_turns": 1,
    "smooth": 1,
    "rideable": 2,
    # safe
    "low_traffic": 3,
    "few_intersections": 1,
    "slow": 2,
    "few_lanes": 1,
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


def _per_km_score(count, km, half):
    """Turns a count per km into 0-1, where `half` per km scores 0.5 and none scores 1."""
    return half / (half + count / km) if km else None


def _is_low_traffic(edge):
    return (
        edge.get("use") in CAR_FREE_USES
        or edge.get("cycle_lane") in SEPARATED_CYCLE_LANES
        or edge.get("road_class") not in BUSY_ROAD_CLASSES
    )


def _is_walking(edge):
    # riding against the edge's allowed direction means it's a one-way the wrong way
    wrong_way = edge.get("traversability") == ("backward" if edge.get("forward", True) else "forward")
    return edge.get("use") in WALKING_USES or edge.get("sac_scale", 0) > 0 or wrong_way


def _turns(edges):
    """Changes in heading of more than TURN_DEGREES between consecutive road segments."""
    # segments inside an intersection (e.g. between a divided road's two sides) and roundabouts aren't turns of their
    # own, and would double count the turn they're part of
    segments = [e for e in edges if not e.get("internal_intersection") and not e.get("roundabout")]
    turns = 0
    for a, b in zip(segments, segments[1:]):
        if "end_heading" not in a or "begin_heading" not in b:
            continue
        change = abs((b["begin_heading"] - a["end_heading"] + 180) % 360 - 180)
        turns += change > TURN_DEGREES
    return turns


def _intersections(edges):
    """Nodes along the route where it crosses or meets a road that cars can use, other than service roads/driveways."""
    return sum(
        any(
            i.get("use") == "road" and i.get("driveability", "none") != "none"
            for i in e.get("end_node", {}).get("intersecting_edges", [])
        )
        for e in edges[:-1]
    )


def _climb(edges):
    """Total elevation gain in meters, from the change in mean elevation between consecutive edges."""
    elevations = [e["mean_elevation"] for e in edges if e.get("mean_elevation") is not None]
    return sum(max(b - a, 0) for a, b in zip(elevations, elevations[1:]))


def score(edges):
    """Returns metrics for a map-matched route (0-1, higher is better, unless named otherwise), plus a 0-100 score."""
    km = sum(e["length"] for e in edges)
    # only roads have speed limits and lanes; unknown speed limits are left out rather than guessed
    roads = [e for e in edges if e.get("use") not in CAR_FREE_USES]
    posted = [e for e in roads if e.get("speed_limit")]
    turns = _turns(edges)
    intersections = _intersections(edges)
    metrics = {
        "distance_km": km,
        # easy
        "gentle": _share(edges, lambda e: e.get("max_upward_grade", 0) < STEEP_GRADE),
        "climb_m": _climb(edges),
        "few_turns": _per_km_score(turns, km, HALF_SCORE_TURNS_PER_KM),
        "turns_per_km": turns / km if km else None,
        "smooth": _share(edges, lambda e: e.get("surface") not in ROUGH_SURFACES),
        "rideable": _share(edges, lambda e: not _is_walking(e)),
        # safe
        "low_traffic": _share(edges, _is_low_traffic),
        "few_intersections": _per_km_score(intersections, km, HALF_SCORE_INTERSECTIONS_PER_KM),
        "intersections_per_km": intersections / km if km else None,
        "slow": _share(posted, lambda e: e["speed_limit"] < FAST_KPH) if posted else None,
        "few_lanes": _share(roads, lambda e: e.get("lane_count", 1) <= 2) if roads else 1.0,
        "bike_network": _share(edges, lambda e: bool(e.get("bicycle_network"))),
    }
    scored = {k: w for k, w in WEIGHTS.items() if metrics[k] is not None}
    metrics["score"] = 100 * sum(metrics[k] * w for k, w in scored.items()) / sum(scored.values())
    return metrics


async def score_route(points):
    return score(await get_edges(points))
