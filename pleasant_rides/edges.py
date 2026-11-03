"""What the road segments (edges) a route follows are like, and what happens between them, for the metrics."""

from .map_matching import Edge
from .units import KM_PER_MILE, METERS_PER_FOOT

# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
BUSY_ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary"}
CAR_FREE_USES = {
    "cycleway",
    "path",
    "footway",
    "pedestrian",
    "mountain_bike",
    "living_street",
    "track",
    "steps",
}
SEPARATED_CYCLE_LANES = {"dedicated", "separated"}
# pavement, boardwalks, and crushed gravel (OSM's "compacted"/"fine_gravel") are all fine
ROUGH_SURFACES = {"dirt", "gravel", "path", "impassable"}
# where you'd usually have to get off and walk
WALKING_USES = {"steps", "footway", "pedestrian", "sidewalk"}

SLOW_MPH = 30  # and under
STEEP_GRADE = 6  # percent
TURN_DEGREES = 45  # a smaller change in heading between road segments is just a bend


def is_low_traffic(edge: Edge):
    return (
        edge.get("use") in CAR_FREE_USES
        or edge.get("cycle_lane") in SEPARATED_CYCLE_LANES
        or edge.get("road_class") not in BUSY_ROAD_CLASSES
    )


def is_walking(edge: Edge):
    # riding against the edge's allowed direction means it's a one-way the wrong way
    wrong_way = edge.get("traversability") == (
        "backward" if edge.get("forward", True) else "forward"
    )
    return edge.get("use") in WALKING_USES or edge.get("sac_scale", 0) > 0 or wrong_way


def turns(edges: list[Edge]):
    """Changes in heading of more than TURN_DEGREES between consecutive road segments."""
    # segments inside an intersection (e.g. between a divided road's two sides) and roundabouts aren't turns of their
    # own, and would double count the turn they're part of
    segments = [
        e
        for e in edges
        if not e.get("internal_intersection") and not e.get("roundabout")
    ]
    turns = 0
    for a, b in zip(segments, segments[1:]):
        if "end_heading" not in a or "begin_heading" not in b:
            continue
        change = abs((b["begin_heading"] - a["end_heading"] + 180) % 360 - 180)
        turns += change > TURN_DEGREES
    return turns


def intersections(edges: list[Edge]):
    """Nodes along the route where it crosses or meets a road that cars can use, other than service roads/driveways."""
    return sum(
        any(
            i.get("use") == "road" and i.get("driveability", "none") != "none"
            for i in e.get("end_node", {}).get("intersecting_edges", [])
        )
        for e in edges[:-1]
    )


def climb(edges: list[Edge]):
    """Total elevation gain in feet, from the change in mean elevation (in meters) between consecutive edges."""
    elevations = [
        e["mean_elevation"] for e in edges if e.get("mean_elevation") is not None
    ]
    return (
        sum(max(b - a, 0) for a, b in zip(elevations, elevations[1:])) / METERS_PER_FOOT
    )


def roads(edges: list[Edge]):
    """Only roads have speed limits and lanes."""
    return [e for e in edges if e.get("use") not in CAR_FREE_USES]


def is_slow(edge: Edge):
    # Valhalla gives speed limits in km/h, so 30 mph comes back as ~48
    return round(edge["speed_limit"] / KM_PER_MILE) <= SLOW_MPH


def posted(edges: list[Edge]):
    """Roads with a known speed limit; unknown limits are left out rather than guessed."""
    return [e for e in roads(edges) if e.get("speed_limit")]


def total_km(edges: list[Edge]):
    return sum(e["length"] for e in edges)


def total_miles(edges: list[Edge]):
    return total_km(edges) / KM_PER_MILE


# https://valhalla.github.io/valhalla/api/map-matching/api-reference/#edge-items
_ROAD_CLASSES = {"service_other": "service road", "unclassified": "minor road"}
_CYCLE_LANES = {
    "shared": "shared",
    "dedicated": "painted",
    "separated": "protected",
    "share_busway": "bus/bike",
}
_SURFACES = {
    "paved_smooth": "smooth pavement",
    "paved_rough": "rough pavement",
    "compacted": "compacted gravel",
    "path": "rough path",
}


def describe(edge: Edge):
    """What a road segment is like, e.g. "secondary road, 2 lanes, protected bike lane, paved"."""
    use = edge.get("use", "road")
    if use != "road":
        parts = [use.replace("_", " ")]
    else:
        road_class = edge.get("road_class")
        parts = [
            _ROAD_CLASSES.get(road_class, f"{road_class} road")
            if road_class
            else "road"
        ]
        if lanes := edge.get("lane_count"):
            parts.append(f"{lanes} lane{'' if lanes == 1 else 's'}")
        if (lane := edge.get("cycle_lane", "none")) != "none":
            parts.append(f"{_CYCLE_LANES.get(lane, lane)} bike lane")
    if surface := edge.get("surface"):
        parts.append(_SURFACES.get(surface) or surface.replace("_", " "))
    return ", ".join(parts)
