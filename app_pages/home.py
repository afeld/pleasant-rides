"""The homepage: what this project is, and what it means by a pleasant ride."""

import base64
from pathlib import Path

import streamlit as st

HERE = Path(__file__).parent


def svg_url(name: str):
    """A CSS url() of an SVG file. It's embedded because st.html removes inline SVGs."""
    data = base64.b64encode((HERE / name).read_bytes()).decode()
    return f"url(data:image/svg+xml;base64,{data})"


st.html(HERE / "home.css")
st.html(
    f"<style>.st-key-home-hero {{ --sky: {svg_url('home-sky.svg')}; --meadow: {svg_url('home-meadow.svg')}; }}</style>"
)

with st.container(key="home-hero", horizontal_alignment="center"):
    st.title(":green-background[Pleasant] Rides", text_alignment="center")
    st.markdown(
        'Mapping apps are good at getting you from place to place, but they generally optimize for minimum travel time. For travel by bike, that isn\'t always desirable. This project is exploring what it would mean to find the "most pleasant" bike route from A to B. This applies within cities/towns, and also in more rural areas.',
        width=720,
        text_alignment="center",
    )
    with st.container(horizontal=True, horizontal_alignment="center", key="home-links"):
        st.page_link(
            "app_pages/planner.py", label="Compare routes", icon=":material/route:"
        )
        st.page_link(
            "app_pages/bike_lanes.py", label="Bike lanes", icon=":material/add_road:"
        )
st.caption(
    "Anyone can see the sample trips and the bike lanes. Planning your own trips is by invitation; to run it yourself, see [the README](https://github.com/afeld/pleasant-rides#running).",
    text_alignment="center",
)

st.header("Working definition", text_alignment="center")
st.markdown('A "pleasant" bike ride is:', text_alignment="center")
enjoyable, easy, safe = (
    column.container(key=f"card-{name}", height="stretch")
    for name, column in zip(("enjoyable", "easy", "safe"), st.columns(3))
)
enjoyable.subheader("Enjoyable", icon=":material/park:", anchor=False)
enjoyable.markdown(
    """
    - Things to look at, such as:
      - Nature
      - Good views
    - Points of interest
    - Quiet
    """
)
easy.subheader("Easy", icon=":material/sentiment_satisfied:", anchor=False)
easy.markdown(
    """
    - Avoids steep climbs/descents
    - Simple navigation
      - Not many turns
    - Smooth-ish surface, such as:
      - Pavement
      - Boardwalks (where cycling is permitted)
      - Crushed gravel
    - Minimal walking required, such as:
      - One-ways
      - Stairs
    """
)
safe.subheader("Safe", icon=":material/health_and_safety:", anchor=False)
safe.markdown(
    """
    - Minimal:
      - Vehicular traffic
      - Intersections
    - If there _are_ motor vehicles:
      - A low speed limit
      - The fewer lanes, the better
    - Not _too_ remote
      - Theoretically walkable to somewhere you can get help if you need.
    """
)
st.markdown(
    "A pleasant ride is _not necessarily_ the most direct, but it shouldn't add a ton of time over the most direct route, either. Similarly, a pleasant route isn't necessarily the most popular one."
)

st.header("See also")
st.markdown(
    """
    - [Cyclemate](https://cyclemate.club/)
      - [Methodology](https://cyclemate.club/supersafe)
    """
)
