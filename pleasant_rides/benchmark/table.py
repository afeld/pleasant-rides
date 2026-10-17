"""The Benchmark page's results table."""

import statistics
from collections.abc import Mapping

from .runner import TripResult, TripScore
from .variants import TRIPS, VARIANTS


def short(trip: str):
    """e.g. "Long" from "Long: Brooklyn→Beacon"."""
    return trip.split(":")[0]


def table_row(name: str, trips: Mapping[str, TripResult]):
    """A variant's row in the results table.

    The mean score and total routing time are only filled in when every trip worked, since they're only comparable then.
    """
    scored = [r for r in trips.values() if isinstance(r, TripScore)]
    complete = len(scored) == len(TRIPS)
    cells = {}
    for trip, result in trips.items():
        ok = isinstance(result, TripScore)
        cells[f"{short(trip)} score"] = result.score if ok else None
        cells[f"{short(trip)} km"] = result.km if ok else None
        cells[f"{short(trip)} s"] = result.seconds if ok else None
    return {
        "Variant": name,
        "Provider": VARIANTS[name].name,
        "Mean": statistics.mean(r.score for r in scored) if complete else None,
        "Routing s": sum(r.seconds for r in scored) if complete else None,
        **cells,
    }
