"""The last benchmark run's results for a selection of variants, kept in Streamlit's disk cache so the Benchmark page can show them without running it again.

Streamlit's caches only remember what a function returned, so `_stored()` stands in for a store: called with a run, it returns (and so caches) that run, and called without one, it returns the cached run or raises an error, which isn't cached. Like the other cached data, it survives restarting the app, and "Clear cache" from the app's ⋮ menu clears it.
"""

from dataclasses import dataclass
from datetime import datetime

import streamlit as st

from .runner import Results


@dataclass(frozen=True)
class LastRun:
    names: list[str]
    results: Results
    finished: datetime
    seconds: float


class _NotRun(Exception):
    pass


# `_run` is left out of the cache key (Streamlit skips parameters starting with an underscore), so a run is stored under the variant names alone
@st.cache_data(show_spinner=False, persist="disk")
def _stored(names: tuple[str, ...], _run: LastRun | None = None) -> LastRun:
    if _run is None:
        raise _NotRun
    return _run


def save(run: LastRun):
    """Replaces the stored run for the same variants."""
    names = tuple(run.names)
    _stored.clear(names)
    _stored(names, run)


def load(names: list[str]):
    """The last run of exactly these variants, or None if there isn't one."""
    try:
        return _stored(tuple(names))
    except _NotRun:
        return None
