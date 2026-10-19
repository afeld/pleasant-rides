import asyncio
import time

import streamlit as st

from pleasant_rides.cached import fetch_routes, geocode, get_edges, get_surroundings
from pleasant_rides.map import build_map
from pleasant_rides.metrics import Metric, Ride
from pleasant_rides.models import Route
from pleasant_rides.providers import PROVIDERS, iter_routes, redact
from pleasant_rides.scoring import METRICS, Scorecard, score
from pleasant_rides.surroundings import Surroundings
from pleasant_rides.trips import TRIPS

st.title("Pleasant Ride Planner")

CUSTOM_TRIP = "Custom…"


def custom_trip():
    """The origin and destination typed in, geocoded."""
    # a form, so that editing a field doesn't trigger a rerun (and a round of API calls) on its own
    with st.form("route"):
        col1, col2 = st.columns(2)
        origin = col1.text_input("Origin", "Brooklyn, NY")
        destination = col2.text_input("Destination", "Beacon, NY")
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
)
origin_point, destination_point = custom_trip() if trip == CUSTOM_TRIP else TRIPS[trip]

status = st.empty()
warnings = st.container()
MAP_HEIGHT = 700
# Streamlit swaps in a new iframe whenever the map changes. A fixed height keeps the page from briefly shrinking in
# between, which would make the browser scroll back to the top.
# (a bit taller than the map itself, which otherwise doesn't quite fit and scrolls)
map_placeholder = st.container(height=MAP_HEIGHT + 16, border=False).empty()

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


def draw_map(provider_routes: dict[str, list[Route]]):
    routes = all_routes(provider_routes)
    if routes:
        highlight = next((r for r in routes if r.id == highlight_id), None)
        with map_placeholder:
            st.iframe(
                build_map(routes, highlight).get_root().render(),
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
        return

    status.caption("Scoring routes…")
    await show_scores(provider_routes)
    status.empty()


def column(metric: Metric):
    if metric.format == "percent":
        return st.column_config.ProgressColumn(
            metric.label, help=metric.help, format=metric.format
        )
    return st.column_config.NumberColumn(
        metric.label, help=metric.help or None, format=metric.format
    )


async def show_scores(provider_routes: dict[str, list[Route]]):
    scored = await score_routes(all_routes(provider_routes))
    scored.sort(key=lambda pair: pair[1].total, reverse=True)
    st.session_state[f"{table_key}:ids"] = [route.id for route, _ in scored]
    show_score_table(scored)


async def score_routes(routes: list[Route]):
    """Returns [(route, Scorecard), ...], warning about any routes that couldn't be scored."""
    # the surroundings of all the routes are fetched at once, since they mostly overlap
    surroundings_task = asyncio.create_task(
        get_surroundings(tuple(route.points for route in routes))
    )
    results = await asyncio.gather(
        *(get_edges(route.points) for route in routes), return_exceptions=True
    )
    surroundings = await surroundings_or_warn(surroundings_task)
    scored: list[tuple[Route, Scorecard]] = []
    for route, result in zip(routes, results):
        if isinstance(result, BaseException):
            st.warning(
                redact(
                    f"{route.provider} {route.label}: couldn't score ({type(result).__name__}: {result})"
                )
            )
        else:
            scored.append((route, score(Ride(route.points, result, surroundings))))
    return scored


async def surroundings_or_warn(task: asyncio.Task[Surroundings]):
    try:
        return await task
    except Exception as error:
        st.warning(
            f"Couldn't get the routes' surroundings from Overture Maps, so scenery, points of interest, and remoteness aren't scored ({type(error).__name__}: {error})"
        )
        return None


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
    st.caption("Select a row to highlight that route on the map.")
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


asyncio.run(show_routes())
