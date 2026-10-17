import asyncio
import time

import streamlit as st
import streamlit.components.v1 as components

from pleasant_rides.geocode import geocode_place
from pleasant_rides.map import build_map
from pleasant_rides.models import Route
from pleasant_rides.providers import PROVIDERS, fetch_routes, iter_routes, redact
from pleasant_rides.scoring import METRICS, Metric, Share, score_route

st.set_page_config(page_title="Pleasant Rides", layout="wide")
st.title("Pleasant Ride Planner")

# cache API calls, so reruns from code changes don't hit the providers again.
# Routes are cached per provider, so one that fails (which isn't cached) gets retried without refetching the others.
geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)
cached_fetch_routes = st.cache_data(show_spinner=False)(fetch_routes)
cached_score_route = st.cache_data(show_spinner=False)(score_route)

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
            components.html(
                build_map(routes, highlight).get_root().render(), height=MAP_HEIGHT
            )


async def show_routes():
    provider_routes = {}
    pending = set(PROVIDERS)
    status.caption(f"Waiting on: {', '.join(sorted(pending))}")
    started = time.monotonic()
    async for name, routes, error in iter_routes(
        origin_point, destination_point, fetch=cached_fetch_routes
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
    if isinstance(metric, Share):
        return st.column_config.ProgressColumn(
            metric.label, help=metric.help, format=metric.format
        )
    return st.column_config.NumberColumn(
        metric.label, help=metric.help or None, format=metric.format
    )


async def show_scores(provider_routes: dict[str, list[Route]]):
    routes = all_routes(provider_routes)
    results = await asyncio.gather(
        *(cached_score_route(route.points) for route in routes), return_exceptions=True
    )
    scored = []
    for route, result in zip(routes, results):
        if isinstance(result, BaseException):
            st.warning(
                redact(
                    f"{route.provider} {route.label}: couldn't score ({type(result).__name__}: {result})"
                )
            )
        else:
            scored.append((route, result))
    scored.sort(key=lambda pair: pair[1].total, reverse=True)
    st.session_state[f"{table_key}:ids"] = [route.id for route, _ in scored]
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
    st.caption("Scenery, points of interest, and remoteness aren't scored yet.")


asyncio.run(show_routes())
