import streamlit as st

st.set_page_config(page_title="Pleasant Rides", page_icon="🚲", layout="wide")
page = st.navigation(
    [
        st.Page("app_pages/planner.py", title="Planner", default=True),
        st.Page("app_pages/benchmark.py", title="Benchmark"),
        st.Page("app_pages/bike_lanes.py", title="Bike lanes", url_path="bike-lanes"),
    ],
    position="top",
)
# the footer is drawn before the page runs, under a container the page then fills, so that it's also under pages that stop early (e.g. to ask the viewer to sign in), since nothing after st.stop() is drawn
body = st.container()
st.divider()
st.caption(
    ":material/code: [Source code on GitHub](https://github.com/afeld/pleasant-rides)"
)
with body:
    page.run()
