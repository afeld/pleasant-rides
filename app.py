import streamlit as st

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.navigation(
    [
        st.Page("app_pages/planner.py", title="Planner", default=True),
        st.Page("app_pages/benchmark.py", title="Benchmark"),
    ],
    position="top",
).run()
