import asyncio
import time

import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.providers import PROVIDERS, fetch_routes, iter_routes, redact
from pleasant_rides.scoring import FAST_KPH, STEEP_GRADE, TURN_DEGREES, score_route

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.title("Pleasant Ride Planner")

# cache API calls, so reruns from code changes don't hit the providers again.
# Routes are cached per provider, so one that fails (which isn't cached) gets retried without refetching the others.
geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)
cached_fetch_routes = st.cache_data(show_spinner=False)(fetch_routes)
cached_score_route = st.cache_data(show_spinner=False)(score_route)

# a form, so that editing a field doesn't trigger a rerun (and a round of API calls) on its own
with st.form("route"):
    col1, col2 = st.columns(2)
    origin = col1.text_input("Origin", "Brooklyn, NY")
    destination = col2.text_input("Destination", "Beacon, NY")
    st.form_submit_button("Route")

try:
    # only the coordinates, so the rest of the geocoder response doesn't affect the cache keys
    origin_point = {k: geocode(origin)[k] for k in ("lat", "lon")}
    destination_point = {k: geocode(destination)[k] for k in ("lat", "lon")}
except IndexError:
    st.error("Couldn't find one of those places.")
    st.stop()

status = st.empty()
warnings = st.container()
MAP_HEIGHT = 700
# Streamlit swaps in a new iframe whenever the map changes. A fixed height keeps the page from briefly shrinking in
# between, which would make the browser scroll back to the top.
# (a bit taller than the map itself, which otherwise doesn't quite fit and scrolls)
map_placeholder = st.container(height=MAP_HEIGHT + 16, border=False).empty()

PARTIAL_MAP_AFTER_S = 1

# keyed by the places, so a new search starts without a selection
table_key = f"scores:{origin_point}:{destination_point}"
# the (provider, label) of each row, saved when the table was drawn, since selections only give row numbers
row_ids = st.session_state.get(f"{table_key}:ids", [])
selected_rows = st.session_state[table_key].selection.rows if table_key in st.session_state else []
highlight = row_ids[selected_rows[0]] if selected_rows else None


def draw_map(provider_routes):
    # keep the layers in a consistent order
    ordered = {n: provider_routes[n] for n in PROVIDERS if provider_routes.get(n)}
    if ordered:
        with map_placeholder:
            components.html(build_map(ordered, highlight).get_root().render(), height=MAP_HEIGHT)


async def show_routes():
    provider_routes = {}
    pending = set(PROVIDERS)
    status.caption(f"Waiting on: {', '.join(sorted(pending))}")
    started = time.monotonic()
    async for name, routes, error in iter_routes(origin_point, destination_point, fetch=cached_fetch_routes):
        pending.discard(name)
        if error:
            warnings.warning(error)
        else:
            provider_routes[name] = routes
        status.caption(f"Waiting on: {', '.join(sorted(pending))}" if pending else "")

        # show partial results while waiting on slow providers. Cached ones all come back at once, so redrawing for
        # each of those would only make the map flicker.
        if pending and time.monotonic() - started > PARTIAL_MAP_AFTER_S:
            draw_map(provider_routes)

    draw_map(provider_routes)
    if not any(provider_routes.values()):
        st.error("No provider returned a route.")
        return

    status.caption("Scoring routes…")
    await show_scores(provider_routes)
    status.empty()


async def show_scores(provider_routes):
    routes = [
        (provider, label, points)
        for provider in PROVIDERS
        for label, points in provider_routes.get(provider) or []
    ]
    results = await asyncio.gather(
        *(cached_score_route(points) for _, _, points in routes), return_exceptions=True
    )
    rows = []
    for (provider, label, _), result in zip(routes, results):
        if isinstance(result, Exception):
            st.warning(redact(f"{provider} {label}: couldn't score ({type(result).__name__}: {result})"))
        else:
            rows.append({"Provider": provider, "Route": label, **result})
    rows.sort(key=lambda row: row["score"], reverse=True)
    st.session_state[f"{table_key}:ids"] = [(row["Provider"], row["Route"]) for row in rows]

    share = st.column_config.ProgressColumn
    st.subheader("Scores")
    st.caption("Select a row to highlight that route on the map.")
    st.dataframe(
        rows,
        key=table_key,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        column_config={
            "score": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=100),
            "distance_km": st.column_config.NumberColumn("Distance (km)", format="%.0f"),
            # easy
            "gentle": share("Gentle", help=f"Grades under {STEEP_GRADE}%", format="percent"),
            "climb_m": st.column_config.NumberColumn("Climb (m)", format="%.0f"),
            "turns_per_km": st.column_config.NumberColumn("Turns/km", help=f"Changes in direction over {TURN_DEGREES}°", format="%.1f"),
            "smooth": share("Smooth", help="Pavement, boardwalks, or crushed gravel", format="percent"),
            "rideable": share("Rideable", help="Not stairs, footways, or the wrong way down a one-way", format="percent"),
            # safe
            "low_traffic": share("Low traffic", help="Off-road, separated bike lane, or not a primary/secondary road or above", format="percent"),
            "intersections_per_km": st.column_config.NumberColumn("Intersections/km", help="With roads open to cars, other than service roads", format="%.1f"),
            "slow": share("Slow", help=f"Speed limit under {FAST_KPH} km/h, of roads with a known limit", format="percent"),
            "few_lanes": share("1-2 lanes", help="Of roads", format="percent"),
            "bike_network": share("Bike network", help="On a designated bike route", format="percent"),
        },
        column_order=[
            "Provider", "Route", "score", "distance_km",
            "gentle", "climb_m", "turns_per_km", "smooth", "rideable",
            "low_traffic", "intersections_per_km", "slow", "few_lanes", "bike_network",
        ],
    )
    st.caption("Scenery, points of interest, and remoteness aren't scored yet.")


asyncio.run(show_routes())
