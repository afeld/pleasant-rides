"""The Benchmark page's results table."""

import statistics
from collections.abc import Mapping

from ..providers import redact
from ..trips import TRIPS, short
from ..units import KM_PER_MILE
from .runner import TripResult, TripScore
from .variants import VARIANTS


def table_row(name: str, trips: Mapping[str, TripResult]):
    """A variant's row in the results table.

    Trips that haven't been scored yet are left blank, and ones that failed are listed under Errors with why. The overall score (the average of the trips' scores) and total routing time are only filled in when every trip worked, since they're only comparable then.
    """
    scored = [r for r in trips.values() if isinstance(r, TripScore)]
    complete = len(scored) == len(TRIPS)
    cells = {}
    errors = []
    for trip in TRIPS:
        result = trips.get(trip)
        ok = isinstance(result, TripScore)
        cells[f"{short(trip)} score"] = result.score if ok else None
        cells[f"{short(trip)} mi"] = result.km / KM_PER_MILE if ok else None
        cells[f"{short(trip)} s"] = result.seconds if ok else None
        if isinstance(result, str):
            errors.append(redact(f"{short(trip)}: {result}"))
    return {
        "Variant": name,
        "Provider": VARIANTS[name].name,
        "Score": statistics.mean(r.score for r in scored) if complete else None,
        "Routing s": sum(r.seconds for r in scored) if complete else None,
        # before the trips' columns, so that it shows without scrolling
        "Errors": "; ".join(errors) or None,
        **cells,
    }
