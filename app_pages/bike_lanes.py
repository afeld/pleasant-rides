import pandas as pd
import pydeck as pdk
import streamlit as st

from pleasant_rides import bike_lanes
from pleasant_rides.cached import compare_bike_lanes

st.title("Bike lanes")
st.caption(
    "New York City's bike lanes as mapped in OpenStreetMap, Overture Maps, and NYC DOT's [bike routes](https://data.cityofnewyork.us/d/mzxg-pwib) on NYC Open Data. "
    f"A stretch of lane counts as being in another source if one of its lanes is within {bike_lanes.MATCH_DISTANCE_M} m, whatever its type, since the sources draw on-street lanes in different places (NYC Open Data on the street's centerline, OpenStreetMap often along the curb)."
)

try:
    compared, as_of = compare_bike_lanes()
except Exception as e:
    # nothing's cached when fetching fails, so reloading the page tries again
    st.error(f"{type(e).__name__}: {e}", title="Couldn't fetch the bike lanes")
    st.stop()

COLORS = {
    bike_lanes.OSM: [126, 188, 111],
    bike_lanes.OVERTURE: [131, 56, 236],
    bike_lanes.NYC: [244, 162, 97],
}

with st.container(horizontal=True):
    for source, frame in compared.items():
        st.metric(
            source,
            f"{frame['length_m'].sum() / 1000:,.0f} km",
            help=f"Data as of {as_of[source]}",
            border=True,
        )

st.subheader("Length by type")
st.caption(
    "Overture's transportation data doesn't say which roads have bike lanes, only which roads and paths bikes are designated to use, so it has no painted lanes. Lanes on both sides of a street can be one line or two, depending on the source."
)
st.dataframe(
    bike_lanes.lengths_by_category(compared),
    column_config={
        source: st.column_config.NumberColumn(f"{source} (km)", format="%.0f")
        for source in compared
    },
    alt="Kilometers of bike lanes of each type in each source",
)

st.subheader("Overlap")
category = st.segmented_control(
    "Type of lane",
    ["All", *bike_lanes.CATEGORIES],
    default="All",
    help="Only counts the lanes of this type in each row's source. The other sources' lanes can be of any type.",
)
st.caption("How much of each row's source's lanes each column's source also has.")
st.dataframe(
    bike_lanes.overlap(compared, None if category in (None, "All") else category) * 100,
    column_config={
        source: st.column_config.ProgressColumn(
            source, format="%.0f%%", min_value=0, max_value=100
        )
        for source in compared
    },
    alt="Share of each source's bike lanes that each other source also has",
)

st.subheader("Map")
with st.container(horizontal=True, vertical_alignment="bottom"):
    sources = st.pills(
        "Sources", list(compared), selection_mode="multi", default=list(compared)
    )
    categories = st.pills(
        "Types",
        bike_lanes.CATEGORIES,
        selection_mode="multi",
        default=bike_lanes.CATEGORIES,
    )
    missing_only = st.toggle(
        "Only what the others don't have",
        help=f"Only show lanes that none of the other selected sources have within {bike_lanes.MATCH_DISTANCE_M} m",
    )


def also_in(frame: pd.DataFrame, others: list[str]):
    """E.g. "OpenStreetMap 100%, NYC Open Data 40%", for the tooltip."""
    if not others:
        return pd.Series("", index=frame.index)
    parts = [
        source + " " + (frame[source] * 100).round().astype(int).astype(str) + "%"
        for source in others
    ]
    return pd.concat(parts, axis=1).agg(", ".join, axis=1)


def layer(source: str):
    frame = compared[source]
    frame = frame.loc[frame["category"].isin(categories)]
    others = [s for s in sources if s != source]
    if missing_only and others:
        frame = frame.loc[frame[others].max(axis=1) < 0.5]
    data = pd.DataFrame(
        {
            "path": frame["path"],
            "source": source,
            "category": frame["category"],
            "name": frame["name"].fillna("(unnamed)"),
            "also_in": also_in(frame, others),
        }
    )
    return pdk.Layer(
        "PathLayer",
        data,
        id=source,
        get_path="path",
        get_color=COLORS[source],
        width_min_pixels=2,
        get_width=4,
        pickable=True,
        auto_highlight=True,
    )


st.markdown(
    " ".join(
        f":material/horizontal_rule: <span style='color: rgb({', '.join(map(str, COLORS[s]))})'>{s}</span>"
        for s in sources
    ),
    unsafe_allow_html=True,
)
st.pydeck_chart(
    pdk.Deck(
        # NYC Open Data, then OpenStreetMap, then Overture on top, so the sources with fewer lanes aren't hidden under the others
        layers=[layer(source) for source in reversed(compared) if source in sources],
        initial_view_state=pdk.ViewState(latitude=40.71, longitude=-73.95, zoom=10.5),
        # Streamlit's default, a light or dark base map to match the app's theme; pydeck's type hints don't allow it, or a template for the tooltip
        map_style=None,  # pyright: ignore[reportArgumentType]
        tooltip={"html": "<b>{source}</b>: {category}<br>{name}<br>Also in: {also_in}"},  # pyright: ignore[reportArgumentType]
    ),
    height=700,
    alt="Map of New York City's bike lanes in each source",
)
