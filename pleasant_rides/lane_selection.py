"""The Bike lanes page's map: the lanes to draw, which of them are picked, and exporting them as GeoJSON.

This is separate from `bike_lanes`, since that module's source is part of the cache key for Overture's lanes.
"""

import json
from collections.abc import Mapping, Sequence

import geopandas as gpd
import pandas as pd
import pydeck as pdk
import shapely
from pydeck.bindings.json_tools import default_serialize

from .bike_lanes import METRIC_CRS, map_paths

# what a lane's tooltip on the map shows, so lanes alike in all of these can be drawn as one line
_TOOLTIP_KEYS = ["category", "name", "updated"]
# the share of a lane another source has for it to count as having it
HAS_SHARE = 0.5
PROPERTIES = ["id", "name", "category", "updated", "length_m"]


def map_lanes(frame: gpd.GeoDataFrame, others: Sequence[str]):
    """A source's lanes (from `bike_lanes.compare()`) for the map, with connected ones that have the same type, name, day they were last edited, and share (to the percent) in each of the `others` merged into one line, each with its `path` (see `bike_lanes.map_paths()`). Each line's tooltip is sent with it, so drawing a street as one line rather than one per block about halves what's sent to the browser."""
    keys = [*_TOOLTIP_KEYS, *others]
    lanes = gpd.GeoDataFrame(
        frame.assign(
            updated=frame["updated"].str[:10], **{o: frame[o].round(2) for o in others}
        )
    ).explode(index_parts=False)
    merged = (
        lanes.groupby(keys, dropna=False, sort=False)
        .geometry.agg(lambda g: shapely.line_merge(shapely.multilinestrings(g.values)))
        .reset_index()
    )
    merged = gpd.GeoDataFrame(merged, crs=frame.crs).explode(ignore_index=True)
    merged["path"] = map_paths(merged)
    return merged.drop(columns="geometry")


def select(
    compared: Mapping[str, pd.DataFrame],
    sources: Sequence[str],
    categories: Sequence[str],
    missing_only: bool,
):
    """Source -> its lanes (from `bike_lanes.compare()` or `map_lanes()`) in `categories`, for each of `sources`; if `missing_only`, only the ones none of the other `sources` have."""
    selected = {}
    for source in sources:
        frame = compared[source]
        frame = frame.loc[frame["category"].isin(categories)]
        others = [s for s in sources if s != source]
        if missing_only and others:
            frame = frame.loc[frame[others].max(axis=1) < HAS_SHARE]
        selected[source] = frame
    return selected


class CompactDeck(pdk.Deck):
    """A pydeck map whose JSON has no indentation, which pydeck adds, since with the whole city's lanes that doubled it, from 9 MB to 19 MB, helping run the deployed app out of memory."""

    def to_json(self):
        return json.dumps(
            self, sort_keys=True, default=default_serialize, separators=(",", ":")
        )


def to_geojson(selected: Mapping[str, gpd.GeoDataFrame]):
    """The lanes from `select()` as a GeoJSON FeatureCollection in lat/lon, with each one's source, ID, name, type, when it was last updated (only OpenStreetMap says), and length in meters."""
    frames = [
        frame[[*PROPERTIES, "geometry"]].assign(source=source)
        for source, frame in selected.items()
    ]
    if not frames:
        return json.dumps({"type": "FeatureCollection", "features": []})
    lanes = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=METRIC_CRS)
    lanes["length_m"] = lanes["length_m"].round().astype(int)
    return (
        lanes[["source", *PROPERTIES, "geometry"]]
        .to_crs("EPSG:4326")
        .to_json(drop_id=True)
    )
