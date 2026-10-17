import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.providers import get_all_routes

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.title("Pleasant Ride Planner")

# cache API calls, so reruns from code changes don't hit every provider again
geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)
routes_between = st.cache_data(show_spinner="Fetching routes…")(get_all_routes)

# a form, so that editing a field doesn't trigger a rerun (and a round of API calls) on its own
with st.form("route"):
    col1, col2 = st.columns(2)
    origin = col1.text_input("Origin", "Brooklyn, NY")
    destination = col2.text_input("Destination", "Beacon, NY")
    st.form_submit_button("Route")

try:
    origin_point = geocode(origin)
    destination_point = geocode(destination)
except IndexError:
    st.error("Couldn't find one of those places.")
    st.stop()

provider_routes, skipped = routes_between(origin_point, destination_point)
for message in skipped:
    st.warning(message)
if not provider_routes:
    st.error("No provider returned a route.")
    st.stop()

components.html(build_map(provider_routes).get_root().render(), height=700)
