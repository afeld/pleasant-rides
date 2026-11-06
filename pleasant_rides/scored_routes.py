"""Scores routes for the app's pages, warning about what couldn't be scored rather than failing."""

import asyncio

import streamlit as st

from .cached import get_edges, get_surroundings, score_ride
from .metrics import Ride
from .models import Route
from .providers import redact
from .scoring import Scorecard
from .surroundings import Surroundings


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
            scored.append((route, score_ride(Ride(route.points, result, surroundings))))
    return scored


async def surroundings_or_warn(task: asyncio.Task[Surroundings]):
    try:
        return await task
    except Exception as error:  # noqa: BLE001
        st.warning(
            f"Couldn't get the routes' surroundings from Overture Maps, so scenery, points of interest, and remoteness aren't scored ({type(error).__name__}: {error})"
        )
        return None
