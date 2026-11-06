import asyncio
import time

import pandas as pd
import streamlit as st

from pleasant_rides import login, street_photos
from pleasant_rides.cached import fetch_routes, geocode, get_edges, route_steps
from pleasant_rides.map import Segment, build_map
from pleasant_rides.metrics import Metric
from pleasant_rides.models import Route
from pleasant_rides.providers import PROVIDERS, iter_routes, redact
from pleasant_rides.providers.base import MissingAPIKey
from pleasant_rides.route_details import route_segments
from pleasant_rides.route_preview import RoutePreview, route_miles, step_data
from pleasant_rides.scored_routes import score_routes
from pleasant_rides.scoring import METRICS, Scorecard
from pleasant_rides.trips import CUSTOM_TRIP, TRIPS

st.title("Pleasant Ride Planner")


def custom_trip():
    """The origin and destination typed in, geocoded."""
    # a form, so that editing a field doesn't trigger a rerun (and a round of API calls) on its own
    with st.form("route"):
        col1, col2 = st.columns(2)
        origin = col1.text_input(
            "Origin", "Brooklyn, NY", key="origin", bind="query-params"
        )
        destination = col2.text_input(
            "Destination", "Beacon, NY", key="destination", bind="query-params"
        )
        st.form_submit_button("Route")
    try:
        return geocode(origin), geocode(destination)
    except IndexError:
        st.error("Couldn't find one of those places.")
        st.stop()


trip = st.selectbox(
    "Trip",
    [*TRIPS, CUSTOM_TRIP],
    help="The sample trips from the Benchmark page, or your own",
    # so that the URL links to the trip
    key="trip",
    bind="query-params",
)
if trip == CUSTOM_TRIP and not login.signed_in():
    login.sign_in("plan your own trip")
    st.stop()
origin_point, destination_point = custom_trip() if trip == CUSTOM_TRIP else TRIPS[trip]

status = st.empty()
warnings = st.container()
MAP_HEIGHT = 700
# Streamlit swaps in a new iframe whenever the map changes. A fixed height keeps the page from briefly shrinking in
# between, which would make the browser scroll back to the top.
# (a bit taller than the map itself, which otherwise doesn't quite fit and scrolls)
map_placeholder = st.container(height=MAP_HEIGHT + 16, border=False).empty()
# for the street-level preview's button and messages (see `street_preview_section()`)
preview_area = st.container()

PARTIAL_MAP_AFTER_S = 1

# keyed by the places, so a new search starts without a selection
table_key = f"scores:{origin_point}:{destination_point}"
# the Route.id of each row, saved when the table was drawn, since selections only give row numbers
row_ids = st.session_state.get(f"{table_key}:ids", [])
selected_rows = (
    st.session_state[table_key].selection.rows if table_key in st.session_state else []
)
highlight_id = row_ids[selected_rows[0]] if selected_rows else None


def all_routes(provider_routes: dict[str, list[Route]]):
    """Flattens provider name -> [Route, ...], in a consistent order."""
    return [route for name in PROVIDERS for route in provider_routes.get(name, [])]


def draw_map(
    provider_routes: dict[str, list[Route]],
    preview: RoutePreview | None = None,
):
    """`preview` is the highlighted route's street-level preview."""
    routes = all_routes(provider_routes)
    if routes:
        highlight = next((r for r in routes if r.id == highlight_id), None)
        m = build_map(routes, highlight)
        if preview:
            preview.add_to(m)
        with map_placeholder:
            st.iframe(
                m.get_root().render(),
                height=MAP_HEIGHT,
                alt="Map of the routes",
            )


async def show_routes():
    provider_routes = {}
    pending = set(PROVIDERS)
    status.caption(f"Waiting on: {', '.join(sorted(pending))}")
    started = time.monotonic()
    async for name, routes, error in iter_routes(
        origin_point, destination_point, fetch=fetch_routes
    ):
        pending.discard(name)
        if error:
            warnings.warning(error)
        else:
            provider_routes[name] = routes
        status.caption(f"Waiting on: {', '.join(sorted(pending))}" if pending else "")

        # show partial results while waiting on slow providers. Cached ones all come back at once, so redrawing for
        # each of those would only make the map flicker.
        if pending and time.monotonic() - started > PARTIAL_MAP_AFTER_S:
            draw_map(provider_routes)

    draw_map(provider_routes)
    if not any(provider_routes.values()):
        st.error("No provider returned a route.")
        return None

    status.caption("Scoring routes…")
    highlighted = await show_scores(provider_routes)
    status.empty()
    return highlighted


def column(metric: Metric):
    if metric.format == "percent":
        return st.column_config.ProgressColumn(
            metric.label, help=metric.help, format=metric.format
        )
    return st.column_config.NumberColumn(
        metric.label, help=metric.help or None, format=metric.format
    )


async def show_scores(provider_routes: dict[str, list[Route]]):
    """The highlighted route and its segments, if there is one."""
    scored = await score_routes(all_routes(provider_routes))
    scored.sort(key=lambda pair: pair[1].total, reverse=True)
    st.session_state[f"{table_key}:ids"] = [route.id for route, _ in scored]
    show_score_table(scored)
    highlight = next((r for r, _ in scored if r.id == highlight_id), None)
    if highlight:
        # already fetched (and cached) for scoring
        segments = route_segments(await get_edges(highlight.points))
        return provider_routes, highlight, segments
    return None


# A fragment, so that the preview button only reruns this, rather than scoring all the routes again, which takes ~4 s. Its button and messages are in its own body (in `preview_area`); the map is the only thing it draws outside of it, which it does every time, since Streamlit only lets a fragment rerun write to outside containers it wrote to in the full run.
@st.fragment
def street_preview_section(
    provider_routes: dict[str, list[Route]], route: Route, segments: list[Segment]
):
    preview = asyncio.run(street_preview(route, segments))
    draw_map(provider_routes, preview)


async def street_preview(route: Route, segments: list[Segment]):
    """Mapillary's photos along the route, to step through on the map, once asked for, since finding them the first time takes a few seconds; or None if they weren't asked for or there aren't any."""
    # only for signed-in people, since the token is sent to the browser, where anyone could take it and use up its quota
    if not login.signed_in():
        return None
    try:
        token = street_photos.token()
    except MissingAPIKey as e:
        st.caption(f"Street-level preview: skipped ({e})")
        return None
    # remembered for the route, so that reruns keep the preview (from the cache), so clicking the route still opens it, without opening it again
    key = f"preview:{table_key}:{route.id}"
    just_asked = st.button(
        "Preview street-level photos",
        icon=":material/photo_camera:",
        key=f"{key}:button",
    )
    if just_asked:
        st.session_state[key] = True
    elif not st.session_state.get(key):
        return None
    try:
        with st.spinner("Finding street-level photos…"):
            steps = await route_steps(route.points)
    except Exception as e:  # noqa: BLE001
        st.warning(
            redact(
                f"Couldn't get street-level photos from Mapillary ({type(e).__name__}: {e})"
            )
        )
        return None
    if not steps:
        st.caption("Mapillary doesn't have street-level photos along this route.")
        return None
    return RoutePreview(
        # without their scores, since the swatches they'd color wouldn't mean anything without the route page's legend
        step_data(route.points, steps, [s._replace(score=None) for s in segments]),
        token,
        route_miles(route.points),
        open=just_asked,
    )


def show_score_table(scored: list[tuple[Route, Scorecard]]):
    rows = [
        {
            "Provider": route.provider,
            "Route": route.label,
            "score": card.total,
            **card.values,
        }
        for route, card in scored
    ]
    st.subheader("Scores")
    st.caption(
        "Select a row to highlight that route on the map and get to its details, including sending it to a navigation app."
    )
    st.dataframe(
        rows,
        key=table_key,
        on_select="rerun",
        selection_mode="single-row",
        hide_index=True,
        column_config={
            "score": st.column_config.ProgressColumn(
                "Score", format="%.0f", min_value=0, max_value=100
            ),
            **{m.key: column(m) for m in METRICS},
        },
        column_order=["Provider", "Route", "score", *(m.key for m in METRICS)],
    )
    show_scoring_criteria()


def show_scoring_criteria():
    with st.expander("How routes are scored"):
        st.markdown(
            "Each route's score (0–100) is the weighted average of the criteria below, each scored from no credit to full credit. Criteria that don't apply to a route, like speed limits when none of its roads has a known one, are left out of its average. Road details come from [OpenStreetMap](https://www.openstreetmap.org/), and surroundings from [Overture Maps](https://overturemaps.org/)."
        )
        st.table(
            pd.DataFrame(
                [
                    {
                        "Criterion": m.label,
                        "What counts": m.help,
                        "Weight": f"{m.weight:g}" if m.weight else "",
                        "Scoring": m.scoring_rule,
                    }
                    for m in METRICS
                ]
            ).set_index("Criterion")
        )


def route_details_button(route: Route):
    """A button for the route's own page, which finds it again from these. A button rather than `st.page_link()`, which can't be made to stand out."""
    if not st.button(
        "Route details",
        type="primary",
        icon=":material/arrow_forward:",
        icon_position="right",
    ):
        return
    custom = (
        {"from": st.session_state["origin"], "to": st.session_state["destination"]}
        if trip == CUSTOM_TRIP
        else {}
    )
    st.switch_page(
        "app_pages/route.py",
        query_params={
            "trip_name": trip,
            **custom,
            "provider": route.provider,
            "route": route.label,
        },
    )


highlighted = asyncio.run(show_routes())
# outside the event loop, since fragments can't be async
if highlighted:
    with preview_area:
        route_details_button(highlighted[1])
        street_preview_section(*highlighted)
