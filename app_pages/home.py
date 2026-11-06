"""The homepage: what this project is, and what it means by a pleasant ride."""

import streamlit as st

st.title("Pleasant Rides")
st.markdown(
    'Mapping apps are good at getting you from place to place, but they generally optimize for minimum travel time. For travel by bike, that isn\'t always desirable. This project is exploring what it would mean to find the "most pleasant" bike route from A to B. This applies within cities/towns, and also in more rural areas.'
)

with st.container(horizontal=True):
    st.page_link(
        "app_pages/planner.py", label="Compare routes", icon=":material/route:"
    )
    st.page_link(
        "app_pages/bike_lanes.py", label="Bike lanes", icon=":material/directions_bike:"
    )
st.caption(
    "Anyone can see the sample trips and the bike lanes. Planning your own trips is by invitation; to run it yourself, see [the README](https://github.com/afeld/pleasant-rides#running)."
)

st.header("Working definition")
st.markdown('A "pleasant" bike ride is:')
enjoyable, easy, safe = st.columns(3)
enjoyable.markdown(
    """
    **Enjoyable**

    - Things to look at, such as:
      - Nature
      - Good views
    - Points of interest
    - Quiet
    """
)
easy.markdown(
    """
    **Easy**

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
safe.markdown(
    """
    **Safe**

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
