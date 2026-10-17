import asyncio

import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.providers import PROVIDERS, fetch_routes, iter_routes

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.title("Pleasant Ride Planner")

# cache API calls, so reruns from code changes don't hit the providers again.
# Routes are cached per provider, so one that fails (which isn't cached) gets retried without refetching the others.
geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)
cached_fetch_routes = st.cache_data(show_spinner=False)(fetch_routes)

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


asyncio.run(show_routes())
