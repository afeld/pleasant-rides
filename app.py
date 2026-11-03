import streamlit as st

from pleasant_rides.login import require_login

st.set_page_config(page_title="Pleasant Rides", layout="wide")
require_login()
st.navigation(
    [
        st.Page("app_pages/planner.py", title="Planner", default=True),
        st.Page("app_pages/benchmark.py", title="Benchmark"),
        st.Page("app_pages/bike_lanes.py", title="Bike lanes"),
    ],
    position="top",
).run()
