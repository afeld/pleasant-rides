"""New York City's bike lanes as mapped by three sources, OpenStreetMap, Overture Maps, and NYC Open Data, put into common categories, and how much of each source's lanes the others have too.

Each source is fetched in one go for the whole city, so they're cheap to cache, and comparing them doesn't hit the servers again.
"""

from collections.abc import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.compute as pc
import shapely

from . import http_client, overture, politeness

OSM = "OpenStreetMap"
OVERTURE = "Overture"
NYC = "NYC Open Data"
SOURCES = [OSM, OVERTURE, NYC]

PROTECTED = "Protected / off-street"
PAINTED = "Painted lane"
SHARED = "Shared / signed"
CONNECTOR = "Connector"
# roughly NYC DOT's facility classes I, II, III, and L
CATEGORIES = [PROTECTED, PAINTED, SHARED, CONNECTOR]

# a projection in meters (UTM zone 18N), for lengths and distances
METRIC_CRS = "EPSG:32618"
# how close a lane in one source needs to be to one in another to count as the same lane. Sources draw on-street lanes in different places, e.g. NYC Open Data on the street's centerline and OpenStreetMap often as a separate line along the curb, so this is about half the width of a wide avenue.
MATCH_DISTANCE_M = 20
# how often lanes are sampled to measure how much of them another source has
SAMPLE_SPACING_M = 10

NYC_WIKIDATA = "Q60"
NYC_OSM_RELATION = 175905
# around the five boroughs
NYC_BBOX = (-74.26, 40.49, -73.70, 40.92)

# public Overpass instances, tried in order when one is busy (they often are)
OVERPASS_SERVERS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
_LANE_VALUES = "lane|track|shared_lane|share_busway|opposite_lane|opposite_track"
OVERPASS_QUERY = f"""
[out:json][timeout:300];
area["wikidata"="{NYC_WIKIDATA}"]["boundary"="administrative"]->.nyc;
(
  way["highway"="cycleway"](area.nyc);
  way["highway"]["bicycle"="designated"](area.nyc);
  way["highway"]["cycleway"~"^({_LANE_VALUES})$"](area.nyc);
  way["highway"]["cycleway:both"~"^({_LANE_VALUES})$"](area.nyc);
  way["highway"]["cycleway:left"~"^({_LANE_VALUES})$"](area.nyc);
  way["highway"]["cycleway:right"~"^({_LANE_VALUES})$"](area.nyc);
);
out tags geom;
"""

# OpenStreetMap highway values / Overture classes that are paths rather than roads
PATHS = {"cycleway", "path", "footway", "pedestrian", "bridleway", "steps", "track"}

NYC_FACILITY_CLASSES = {"I": PROTECTED, "II": PAINTED, "III": SHARED, "L": CONNECTOR}


def _frame(rows: list[dict], geometries: list):
    """A GeoDataFrame of lanes, with an `id`, `name`, `category`, and `geometry`, in lat/lon."""
    columns = ["id", "name", "category"]
    return gpd.GeoDataFrame(
        pd.DataFrame(rows, columns=columns), geometry=geometries, crs="EPSG:4326"
    )


def osm_category(tags: dict[str, str]):
    """The category of an OpenStreetMap way, or None if it isn't bike infrastructure."""
    highway = tags.get("highway")
    if highway in (None, "construction", "proposed"):
        return None
    if tags.get("footway") == "crossing" or tags.get("cycleway") == "crossing":
        return CONNECTOR
    if highway in PATHS:
        if highway == "cycleway" or tags.get("bicycle") == "designated":
            return PROTECTED
        return None
    lanes = {
        tags.get(key)
        for key in ("cycleway", "cycleway:both", "cycleway:left", "cycleway:right")
    }
    if lanes & {"track", "opposite_track"}:
        return PROTECTED
    if lanes & {"lane", "opposite_lane"}:
        return PAINTED
    if lanes & {"shared_lane", "share_busway"} or tags.get("bicycle") == "designated":
        return SHARED
    return None


def fetch_osm():
    """The city's bike infrastructure in OpenStreetMap, from the Overpass API, as it returns it, so that changing how it's categorized doesn't need a refetch."""
    for server in OVERPASS_SERVERS:
        try:
            response = http_client.post(
                server, data={"data": OVERPASS_QUERY}, timeout=330
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            # a busy or rate-limited server, so another might work, but a bad query won't work anywhere
            busy = politeness.is_retryable(e) or politeness.is_rate_limited(e)
            if not busy or server == OVERPASS_SERVERS[-1]:
                raise
    raise AssertionError("unreachable")


def parse_osm(data: dict):
    """The lanes in an Overpass response, and when the data is from."""
    rows, geometries = [], []
    for way in data["elements"]:
        tags = way.get("tags", {})
        category = osm_category(tags)
        if category is None or len(way.get("geometry", [])) < 2:
            continue
        rows.append(
            {"id": f"way/{way['id']}", "name": tags.get("name"), "category": category}
        )
        geometries.append(
            shapely.LineString([(node["lon"], node["lat"]) for node in way["geometry"]])
        )
    return _frame(rows, geometries), data["osm3s"]["timestamp_osm_base"]


def fetch_boundary():
    """New York City's boundary in OpenStreetMap, including the water, so that bridges are in it."""
    response = http_client.get(
        "https://nominatim.openstreetmap.org/lookup",
        params={
            "osm_ids": f"R{NYC_OSM_RELATION}",
            "format": "geojson",
            "polygon_geojson": 1,
        },
        timeout=60,
    )
    response.raise_for_status()
    return shapely.geometry.shape(response.json()["features"][0]["geometry"])


def overture_category(
    road_class: str | None, subclass: str | None, access_restrictions: list | None
):
    """The category of an Overture road segment, or None if it isn't bike infrastructure. Overture doesn't say whether roads have bike lanes, only whether bikes are designated to use them."""
    if subclass == "cycle_crossing":
        return CONNECTOR
    designated = any(
        rule["access_type"] == "designated"
        and "bicycle" in ((rule.get("when") or {}).get("mode") or [])
        for rule in access_restrictions or []
    )
    if road_class == "cycleway" or (designated and road_class in PATHS):
        return CONNECTOR if subclass == "crosswalk" else PROTECTED
    if designated:
        return SHARED
    return None


def fetch_overture(release: str, boundary: shapely.Geometry):
    """The city's bike lanes in an Overture release, clipped to `boundary`."""
    files = overture._files(release, "segment", NYC_BBOX)
    table = overture._dataset(files).to_table(
        columns=["id", "names", "class", "subclass", "access_restrictions", "geometry"],
        filter=overture._overlaps(NYC_BBOX) & (pc.field("subtype") == "road"),
    )
    rows, geometries = [], []
    for segment in table.to_pylist():
        category = overture_category(
            segment["class"], segment["subclass"], segment["access_restrictions"]
        )
        if category is None:
            continue
        name = (segment["names"] or {}).get("primary")
        rows.append({"id": segment["id"], "name": name, "category": category})
        geometries.append(shapely.from_wkb(segment["geometry"]))
    lanes = _frame(rows, geometries)
    return lanes[lanes.intersects(boundary)].reset_index(drop=True)


NYC_DATASET = "mzxg-pwib"


def fetch_nyc():
    """The city's current bike lanes in NYC DOT's dataset on NYC Open Data, as GeoJSON, and when it was last updated."""
    response = http_client.get(
        f"https://data.cityofnewyork.us/resource/{NYC_DATASET}.geojson",
        params={"$where": "status = 'Current'", "$limit": 100_000},
        timeout=120,
    )
    response.raise_for_status()
    metadata = http_client.get(
        f"https://data.cityofnewyork.us/api/views/{NYC_DATASET}.json", timeout=60
    )
    metadata.raise_for_status()
    updated = pd.Timestamp(metadata.json()["rowsUpdatedAt"], unit="s")
    return response.json(), updated.isoformat()


def parse_nyc(data: dict):
    """The lanes in NYC Open Data's GeoJSON."""
    rows, geometries = [], []
    for feature in data["features"]:
        props = feature["properties"]
        if not feature["geometry"]:
            continue
        name = props.get("street")
        if name and props.get("fromstreet") and props.get("tostreet"):
            name = f"{name} ({props['fromstreet']} to {props['tostreet']})"
        rows.append(
            {
                "id": props.get("segmentid"),
                "name": name,
                "category": NYC_FACILITY_CLASSES.get(props.get("facilitycl"), SHARED),
            }
        )
        geometries.append(shapely.geometry.shape(feature["geometry"]))
    # one line per row, so they can be sampled along
    return _frame(rows, geometries).explode(ignore_index=True)


def compare(lanes: dict[str, gpd.GeoDataFrame]):
    """Adds to each source's lanes (in `METRIC_CRS`) their `length_m`, and for each other source, the fraction of the lane that's within `MATCH_DISTANCE_M` of one of its lanes, in a column named after it."""
    projected = {
        source: gpd.GeoDataFrame(frame.to_crs(METRIC_CRS).reset_index(drop=True))
        for source, frame in lanes.items()
    }
    trees = {
        source: shapely.STRtree(frame.geometry.values)
        for source, frame in projected.items()
    }
    for source, frame in projected.items():
        frame["length_m"] = frame.length
        lane_of_sample, samples = _samples(frame.geometry.to_numpy())
        for other, tree in trees.items():
            if other == source:
                continue
            near, _ = tree.query(
                samples, predicate="dwithin", distance=MATCH_DISTANCE_M
            )
            matched = np.zeros(len(samples))
            matched[near] = 1
            frame[other] = np.bincount(
                lane_of_sample, weights=matched, minlength=len(frame)
            ) / np.bincount(lane_of_sample, minlength=len(frame))
    return projected


def _samples(geometries: np.ndarray):
    """Points spaced about `SAMPLE_SPACING_M` apart along each line, and the index of the line each is on."""
    counts = np.maximum(
        1, np.ceil(shapely.length(geometries) / SAMPLE_SPACING_M).astype(int)
    )
    lane_of_sample = np.repeat(np.arange(len(geometries)), counts)
    # the middle of each stretch, so short lanes are sampled in the middle rather than at an end
    starts = np.cumsum(counts) - counts
    position = np.arange(counts.sum()) - np.repeat(starts, counts)
    fractions = (position + 0.5) / np.repeat(counts, counts)
    points = shapely.line_interpolate_point(
        geometries[lane_of_sample], fractions, normalized=True
    )
    return lane_of_sample, points


def lengths_by_category(compared: Mapping[str, pd.DataFrame]):
    """Kilometers of lanes in each category (rows), per source (columns)."""
    lengths = pd.concat(
        [
            frame[["category", "length_m"]].assign(source=source)
            for source, frame in compared.items()
        ]
    ).pivot_table(index="category", columns="source", values="length_m", aggfunc="sum")
    return (
        (lengths / 1000)
        .reindex(index=CATEGORIES, columns=list(compared))
        .fillna(0)
        .rename_axis(index="Type", columns=None)
    )


def overlap(compared: Mapping[str, pd.DataFrame], category: str | None = None):
    """The share of each source's lanes (rows) that each other source (columns) also has, optionally only for one category of the source's lanes."""
    rows = {}
    for source, frame in compared.items():
        if category:
            frame = frame.loc[frame["category"] == category]
        total = frame["length_m"].to_numpy().sum()
        rows[source] = {
            other: (frame[other] * frame["length_m"]).sum() / total if total else None
            for other in compared
            if other != source
        }
    return pd.DataFrame(rows).T.reindex(index=list(compared), columns=list(compared))


def map_paths(frame: gpd.GeoDataFrame, simplify_m: float = 2):
    """Each lane's line (in `METRIC_CRS`) as [[lon, lat], ...], simplified and rounded to about a meter, to keep what's sent to the browser small."""
    lines = frame.geometry.simplify(simplify_m).to_crs("EPSG:4326")
    return [np.round(shapely.get_coordinates(line), 5).tolist() for line in lines]
