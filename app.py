import asyncio

import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.providers import PROVIDERS, fetch_routes, iter_routes, redact
from pleasant_rides.scoring import FAST_KPH, STEEP_GRADE, score_route

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
map_placeholder = st.empty()


async def show_routes():
    provider_routes = {}
    pending = set(PROVIDERS)
    status.caption(f"Waiting on: {', '.join(sorted(pending))}")
    async for name, routes, error in iter_routes(origin_point, destination_point, fetch=cached_fetch_routes):
        pending.discard(name)
        if error:
            warnings.warning(error)
        else:
            provider_routes[name] = routes
        status.caption(f"Waiting on: {', '.join(sorted(pending))}" if pending else "")

        # redraw as results come in, keeping the layers in a consistent order
        ordered = {n: provider_routes[n] for n in PROVIDERS if provider_routes.get(n)}
        if ordered:
            with map_placeholder:
                components.html(build_map(ordered).get_root().render(), height=700)

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

    share = st.column_config.ProgressColumn
    st.subheader("Scores")
    st.dataframe(
        rows,
        hide_index=True,
        column_config={
            "score": st.column_config.ProgressColumn("Score", format="%.0f", min_value=0, max_value=100),
            "distance_km": st.column_config.NumberColumn("Distance (km)", format="%.0f"),
            "low_traffic": share("Low traffic", help="Off-road, separated bike lane, or not a primary/secondary road or above", format="percent"),
            "slow": share("Slow", help=f"Speed limit under {FAST_KPH} km/h, of roads with a known limit", format="percent"),
            "few_lanes": share("1-2 lanes", help="Of roads", format="percent"),
            "smooth": share("Smooth", help="Paved, and not marked as rough", format="percent"),
            "gentle": share("Gentle", help=f"Grades under {STEEP_GRADE}%", format="percent"),
            "bike_network": share("Bike network", help="On a designated bike route", format="percent"),
            "climb_m": st.column_config.NumberColumn("Climb (m)", format="%.0f"),
        },
        column_order=["Provider", "Route", "score", "distance_km", "low_traffic", "slow", "few_lanes", "smooth", "gentle", "bike_network", "climb_m"],
    )
    st.caption("Scenery, points of interest, and remoteness aren't scored yet.")


asyncio.run(show_routes())
