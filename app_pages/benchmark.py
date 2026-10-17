import asyncio
import time

import streamlit as st

from pleasant_rides.benchmark.runner import run_variants, steps
from pleasant_rides.benchmark.table import short, table_row
from pleasant_rides.benchmark.variants import VARIANTS
from pleasant_rides.cached import fetch_routes_timed, get_edges, get_surroundings
from pleasant_rides.providers import redact
from pleasant_rides.trips import TRIPS

st.title("Benchmark")
st.caption(
    "Scores each variant's first route on a few sample trips. Variants are defined in `pleasant_rides/benchmark/variants.py`. "
    "Results come from the providers' live servers, so compare against the `(current)` baselines from the same run."
)

with st.form("benchmark"):
    names = st.multiselect("Variants", list(VARIANTS), default=list(VARIANTS))
    if st.form_submit_button("Run"):
        st.session_state.benchmark_names = names

# kept across reruns (e.g. from code changes), which are quick since the results are cached
names: list[str] = st.session_state.get("benchmark_names", [])
if not names:
    st.stop()

progress = st.progress(0.0, text="Running…")
done = 0


def on_step(message: str):
    global done
    done += 1
    progress.progress(done / steps(names), text=message)


started = time.perf_counter()
results = asyncio.run(
    run_variants(names, fetch_routes_timed, get_edges, get_surroundings, on_step)
)
progress.empty()
st.caption(
    f"Ran in {time.perf_counter() - started:.0f} s, reusing cached routes and scoring data where possible. The routing "
    "times are from when the routes were fetched."
)


rows = [table_row(name, results.trips[name]) for name in names]
rows.sort(key=lambda r: (r["Mean"] is not None, r["Mean"] or 0), reverse=True)
# Streamlit's default row height, plus the header, so that every variant shows without scrolling
ROW_HEIGHT_PX = 35
st.dataframe(
    rows,
    hide_index=True,
    width="stretch",
    height=(len(rows) + 1) * ROW_HEIGHT_PX + 3,
    column_config={
        "Mean": st.column_config.ProgressColumn(
            "Mean", format="%.1f", min_value=0, max_value=100
        ),
        **{
            f"{short(t)} score": st.column_config.NumberColumn(
                f"{short(t)} score", help=t, format="%.1f"
            )
            for t in TRIPS
        },
        "Routing s": st.column_config.NumberColumn(
            "Routing s",
            help="Seconds the provider took to return routes, in total across the trips",
            format="%.1f",
        ),
        **{
            f"{short(t)} km": st.column_config.NumberColumn(
                f"{short(t)} km", help=t, format="%.0f"
            )
            for t in TRIPS
        },
        **{
            f"{short(t)} s": st.column_config.NumberColumn(
                f"{short(t)} s", help=f"{t}: seconds to route", format="%.1f"
            )
            for t in TRIPS
        },
    },
)

errors = [
    redact(f"{name}, {trip}: {result}")
    for name in names
    for trip, result in results.trips[name].items()
    if isinstance(result, str)
]
errors += [
    f"{trip}: couldn't get the routes' surroundings from Overture Maps, so scenery, points of interest, and "
    f"remoteness aren't scored ({error})"
    for trip, error in results.surroundings_errors.items()
]
if errors:
    with st.expander(f"Errors ({len(errors)})"):
        st.caption("These aren't cached, so they're retried on the next run.")
        st.markdown("\n".join(f"- {e}" for e in errors))
