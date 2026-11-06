"""The particulars of one route, on its own: linked from the planner, and addressed by its URL's query parameters."""

import asyncio
from typing import NoReturn

import streamlit as st

from pleasant_rides import login
from pleasant_rides.cached import fetch_routes, geocode, get_edges
from pleasant_rides.map import build_map
from pleasant_rides.models import Point, Route
from pleasant_rides.providers import PROVIDERS, redact
from pleasant_rides.route_details import (
    MIXES,
    credit,
    elevation_profile,
    format_value,
    mix,
    route_segments,
    stretches,
)
from pleasant_rides.route_export import (
    MAX_WAYPOINTS,
    MAX_WAYPOINTS_MOBILE,
    RIDE_WITH_GPS_UPLOAD_URL,
    allows_file_export,
    google_maps_url,
    gpx_filename,
    is_mobile,
    to_gpx,
)
from pleasant_rides.scored_routes import score_routes
from pleasant_rides.scoring import METRICS
from pleasant_rides.trips import CUSTOM_TRIP, TRIPS

# shown up top, by metric key
HEADLINE_METRICS = ["distance_mi", "climb_ft", "low_traffic", "turns_per_mi"]
# for values of 0-100, since format="percent" shows two decimal places
PERCENT_COLUMN = st.column_config.ProgressColumn(
    format="%.0f%%", min_value=0, max_value=100
)

# not the names the planner binds its widgets to ("trip", "origin", and "destination"), since Streamlit drops those from the URL when navigating away from the planner
params = st.query_params
trip = params.get("trip_name")
origin_query = params.get("from", "")
destination_query = params.get("to", "")
planner_params = {
    "trip": trip or "",
    **(
        {"origin": origin_query, "destination": destination_query}
        if trip == CUSTOM_TRIP
        else {}
    ),
}

st.page_link(
    "app_pages/planner.py",
    label="All routes for this trip",
    icon=":material/arrow_back:",
    query_params=planner_params,
)


def not_found() -> NoReturn:
    st.error(
        "Couldn't find that route. Providers' routes can change, so try picking it from the planner again."
    )
    st.stop()


def trip_ends() -> tuple[Point, Point]:
    """The trip's origin and destination."""
    if trip in TRIPS:
        return TRIPS[trip]
    if trip != CUSTOM_TRIP:
        not_found()
    if not login.signed_in():
        login.sign_in("see routes for your own trips")
        st.stop()
    try:
        return geocode(origin_query), geocode(destination_query)
    except IndexError:
        not_found()


def export_section(route: Route):
    """Buttons to get the route into a navigation app."""
    max_waypoints = (
        MAX_WAYPOINTS_MOBILE
        if is_mobile(st.context.headers.get("User-Agent"))
        else MAX_WAYPOINTS
    )
    file_export = allows_file_export(route)
    with st.container(horizontal=True):
        if file_export:
            st.download_button(
                "Download GPX",
                # only built when clicked
                lambda: to_gpx(route),
                file_name=gpx_filename(route),
                mime="application/gpx+xml",
                on_click="ignore",
                icon=":material/download:",
                key="action-download-gpx",
            )
            st.link_button(
                "Upload to Ride with GPS",
                RIDE_WITH_GPS_UPLOAD_URL,
                icon=":material/upload:",
                key="action-ride-with-gps",
                help="Opens their upload page, to add the downloaded GPX file to",
            )
        st.link_button(
            "Open in Google Maps",
            google_maps_url(route, max_waypoints),
            icon=":material/navigation:",
            key="action-google-maps",
        )
    exact = " The GPX file has the exact route." if file_export else ""
    st.caption(
        f"Google Maps only gets {max_waypoints} points along the route and picks its own way between them, so it may differ.{exact}"
    )


provider = PROVIDERS.get(params.get("provider", ""))
if not provider:
    not_found()
origin, destination = trip_ends()

try:
    with st.spinner("Getting the route…"):
        routes = asyncio.run(fetch_routes(provider, origin, destination))
except Exception as error:  # noqa: BLE001
    st.error(
        redact(
            f"Couldn't get the route from {provider.name} ({type(error).__name__}: {error})"
        )
    )
    st.stop()
route = next((r for r in routes if r.label == params.get("route")), None)
if not route:
    not_found()

st.title(f"{route.provider}: {route.label}", icon=":material/route:")
st.caption(trip if trip in TRIPS else f"{origin_query} → {destination_query}")

export_section(route)

with st.spinner("Scoring the route…"):
    scored = asyncio.run(score_routes([route]))
if not scored:
    st.iframe(
        build_map([route]).get_root().render(), height=500, alt="Map of the route"
    )
    st.stop()
_, card = scored[0]
# already fetched (and cached) for scoring
edges = asyncio.run(get_edges(route.points))
metrics = {m.key: m for m in METRICS}

with st.container(horizontal=True):
    st.metric(
        "Score",
        f"{card.total:.0f}",
        help="Out of 100; see how it scored, below",
        border=True,
    )
    for key in HEADLINE_METRICS:
        metric = metrics[key]
        st.metric(
            metric.label,
            format_value(metric, card.values[key]),
            help=metric.help or None,
            border=True,
        )

st.iframe(
    build_map([route], route, route_segments(edges)).get_root().render(),
    height=500,
    alt="Map of the route, colored by how each road segment scores",
)

if profile := elevation_profile(edges):
    st.subheader("Elevation")
    st.area_chart(
        profile,
        x="mile",
        y="elevation_ft",
        x_label="Mile",
        y_label="Elevation (ft)",
        height=220,
        alt="Elevation along the route, by mile",
    )

st.subheader("What it rides on")
for column, (name, kind) in zip(st.columns(len(MIXES)), MIXES.items()):
    miles = mix(edges, kind)
    total = sum(m for _, m in miles)
    column.dataframe(
        [{name: k, "Miles": m, "Share": 100 * m / total} for k, m in miles],
        hide_index=True,
        height="content",
        column_config={
            "Miles": st.column_config.NumberColumn(format="%.1f"),
            "Share": PERCENT_COLUMN,
        },
    )

st.subheader("Along the route")
st.caption(
    "From start to end. Scores are of the road itself, like traffic, speed, lanes, grade, surface, and rideability."
)
st.dataframe(
    [
        {
            "Mile": s.start_mi,
            "Length (mi)": s.miles,
            "What it's like": s.description,
            "Score": s.score,
            "Steepest grade": s.steepest_grade,
            "Speed limit (mph)": s.speed_limit_mph,
        }
        for s in stretches(edges)
    ],
    hide_index=True,
    column_config={
        "Mile": st.column_config.NumberColumn(format="%.1f"),
        "Length (mi)": st.column_config.NumberColumn(format="%.2f"),
        "What it's like": st.column_config.TextColumn(width="large"),
        "Score": st.column_config.ProgressColumn(
            format="%.0f", min_value=0, max_value=100
        ),
        "Steepest grade": st.column_config.NumberColumn(format="%.0f%%"),
    },
)

st.subheader("How it scored")
st.caption(
    "The score is the average of the credit for each criterion, weighted. Criteria without credit aren't counted, either because they don't apply to this route or because they're only shown."
)
st.dataframe(
    [
        {
            "Criterion": m.label,
            "Value": format_value(m, card.values[m.key]),
            "Credit": None if (c := credit(card, m)) is None else 100 * c,
            "Weight": m.weight,
            "What counts": m.help,
        }
        for m in METRICS
    ],
    hide_index=True,
    height="content",
    column_config={
        "Credit": PERCENT_COLUMN,
        "Weight": st.column_config.NumberColumn(format="%g"),
        "What counts": st.column_config.TextColumn(width="large"),
    },
)
