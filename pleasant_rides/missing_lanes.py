"""One source's bike lanes that another doesn't have, joined into stretches of street and exported as GeoJSON, e.g. for a MapRoulette challenge of NYC Open Data's lanes that OpenStreetMap is missing.

This is separate from `bike_lanes` since that module's source is part of the cache key for Overture's lanes.
"""

from collections.abc import Mapping

import geopandas as gpd
import pandas as pd
import shapely

# the share of a lane another source has for it to count as missing, matching the bike-lanes map's "Only what the others don't have"
MISSING_SHARE = 0.5
# shorter stretches are mostly where the sources draw a lane a little differently, e.g. ending it at different sides of an intersection
MIN_LENGTH_M = 50
# endpoints this close (in meters) count as the same, so a street's segments join up
SNAP_M = 0.1


def missing(compared: Mapping[str, gpd.GeoDataFrame], source: str, other: str):
    """`source`'s lanes that `other` doesn't have (see `bike_lanes.compare()`), joined end to end by category into stretches between intersections, each with the `ids` and `names` of its lanes, in lat/lon."""
    lanes = compared[source]
    lanes = lanes.loc[lanes[other] < MISSING_SHARE]
    stretches = []
    for category, group in lanes.groupby("category"):
        lines = shapely.set_precision(group.geometry.to_numpy(), SNAP_M)
        merged = shapely.line_merge(shapely.union_all(lines))
        tree = shapely.STRtree(lines)
        for stretch in shapely.get_parts(merged):
            within = tree.query(stretch.buffer(SNAP_M * 10), predicate="contains")
            parts = group.iloc[sorted(within)]
            stretches.append(
                {
                    "category": category,
                    "names": "; ".join(parts["name"].dropna().unique()),
                    "ids": "; ".join(parts["id"].dropna().unique()),
                    "length_m": round(stretch.length),
                    "geometry": stretch,
                }
            )
    frame = gpd.GeoDataFrame(
        pd.DataFrame(
            stretches, columns=["category", "names", "ids", "length_m", "geometry"]
        ),
        crs=lanes.crs,
    )
    frame = frame.loc[frame["length_m"] >= MIN_LENGTH_M]
    return (
        frame.sort_values("length_m", ascending=False)
        .to_crs("EPSG:4326")
        .reset_index(drop=True)
    )


def to_geojson(stretches: gpd.GeoDataFrame):
    """The stretches as a GeoJSON FeatureCollection, one feature per task."""
    return stretches.to_json(drop_id=True)
