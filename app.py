import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.providers import fetch_routes, get_all_routes

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.title("Pleasant Ride Planner")

# cache API calls, so reruns from code changes don't hit the providers again.
# Routes are cached per provider, so one that fails (which isn't cached) gets retried without refetching the others.
geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)
cached_fetch_routes = st.cache_data(show_spinner="Fetching routes…")(fetch_routes)

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

provider_routes, skipped = get_all_routes(origin_point, destination_point, fetch=cached_fetch_routes)
for message in skipped:
    st.warning(message)
if not any(provider_routes.values()):
    st.error("No provider returned a route.")
    st.stop()

components.html(build_map(provider_routes).get_root().render(), height=700)
