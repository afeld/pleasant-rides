import asyncio
import time
from datetime import datetime

import streamlit as st

from pleasant_rides import login
from pleasant_rides.benchmark import last_run
from pleasant_rides.benchmark.last_run import LastRun
from pleasant_rides.benchmark.runner import Results, run_variants, steps
from pleasant_rides.benchmark.table import table_row
from pleasant_rides.benchmark.variants import VARIANTS
from pleasant_rides.cached import (
    fetch_routes_timed,
    get_edges,
    get_surroundings,
    score_ride,
)
from pleasant_rides.trips import TRIPS, short

st.title("Benchmark")
st.caption(
    "Scores each variant's first route on a few sample trips. Variants are defined in `pleasant_rides/benchmark/variants.py`. "
    "Results come from the providers' live servers, so compare against the `(current)` baselines from the same run."
)

if login.signed_in():
    with st.form("benchmark"):
        selected = st.multiselect("Variants", list(VARIANTS), default=list(VARIANTS))
        run_now = st.form_submit_button("Run")
else:
    login.sign_in("run the benchmark")
    selected, run_now = list(VARIANTS), False

progress = st.empty()
summary = st.empty()
table = st.empty()

# Streamlit's default row height, plus the header, so that every variant shows without scrolling
ROW_HEIGHT_PX = 35
COLUMNS = {
    "Score": st.column_config.ProgressColumn(
        "Score",
        help="The average of the trips' scores. Each variant is run once per trip.",
        format="%.1f",
        min_value=0,
        max_value=100,
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
    "Errors": st.column_config.TextColumn(
        "Errors",
        width="medium",
        help="Why trips weren't scored. Failures aren't cached, so they're retried on the next run.",
    ),
    **{
        f"{short(t)} mi": st.column_config.NumberColumn(
            f"{short(t)} mi", help=t, format="%.1f"
        )
        for t in TRIPS
    },
    **{
        f"{short(t)} s": st.column_config.NumberColumn(
            f"{short(t)} s", help=f"{t}: seconds to route", format="%.1f"
        )
        for t in TRIPS
    },
}


def show_table(names: list[str], results: Results):
    rows = [table_row(name, results.trips[name]) for name in names]
    rows.sort(key=lambda r: (r["Score"] is not None, r["Score"] or 0), reverse=True)
    table.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        height=(len(rows) + 1) * ROW_HEIGHT_PX + 3,
        column_config=COLUMNS,
    )


def run(names: list[str]):
    """Runs the benchmark, showing the results as they come in. Saves them after each trip is scored, so that if the run is cut short (e.g. by the app restarting), the trips done so far still show."""
    done = 0
    started = time.perf_counter()
    so_far: Results | None = None

    def save(results: Results, complete: bool):
        finished = LastRun(
            names,
            results,
            datetime.now().astimezone(),
            time.perf_counter() - started,
            complete,
        )
        last_run.save(finished)
        return finished

    def on_step(message: str, results: Results):
        nonlocal done, so_far
        done += 1
        so_far = results
        progress.progress(done / steps(names), text=message)
        # trips appear in the table as they're scored
        if message.startswith("Scored"):
            show_table(names, results)
            save(results, complete=False)

    try:
        results = asyncio.run(
            run_variants(
                names,
                fetch_routes_timed,
                get_edges,
                get_surroundings,
                on_step,
                score_ride,
            )
        )
    except Exception as e:  # noqa: BLE001
        # failures of the providers' calls are already caught per variant and trip, so this would be a bug; the results so far are kept rather than lost with it
        st.exception(e)
        return save(so_far, complete=False) if so_far else None
    finally:
        progress.empty()
    return save(results, complete=True)


def show_surroundings_errors(results: Results):
    errors = [
        f"{trip}: couldn't get the routes' surroundings from Overture Maps, so scenery, points of interest, and remoteness aren't scored ({error})"
        for trip, error in results.surroundings_errors.items()
    ]
    if errors:
        with st.expander(f"Errors ({len(errors)})"):
            st.caption("These aren't cached, so they're retried on the next run.")
            st.markdown("\n".join(f"- {e}" for e in errors))


# only runs when asked to; otherwise, including on reruns from code changes, shows the last run's results
latest = run(selected) if run_now and selected else last_run.load(selected)
if not latest:
    st.caption("These variants haven't been run yet.")
    st.stop()
# leaving out variants that have been renamed or removed since
shown = [name for name in latest.names if name in VARIANTS]
unfinished = (
    ""
    if latest.complete
    else " It didn't finish, so the trips after those shown are missing."
)
summary.caption(
    f"Last run {latest.finished:%b %-d at %-I:%M %p}, in {latest.seconds:.0f} s, reusing cached routes, scoring data, and scores where possible. The routing times are from when the routes were fetched.{unfinished}"
)
show_table(shown, latest.results)
show_surroundings_errors(latest.results)
