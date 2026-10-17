"""Cached versions of the API calls, shared by the app's pages, so reruns don't hit the providers again.

They're persisted to disk, so they also survive restarting the app; use "Clear cache" from the app's ⋮ menu to refetch.
Failures aren't cached (exceptions propagate), so they get retried on the next run, except ones that would only happen again (see `_unless_failed()`). Scores aren't cached, only the data they're computed from, so that changes to the scoring take effect.
"""

import hashlib
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

import streamlit as st

from . import map_matching, providers, surroundings
from .geocode import geocode_place
from .models import Point
from .politeness import ProviderError, is_permanent
from .providers.base import Provider

T = TypeVar("T")

geocode = st.cache_data(show_spinner="Geocoding…", persist="disk")(geocode_place)


# `_provider` is left out of the cache key (Streamlit skips parameters starting with an underscore); `key` stands in
# for it, so that each provider and settings are cached separately. Cached with how long they took, for the Benchmark
# page.
@st.cache_data(show_spinner=False, persist="disk")
async def _fetch_routes_timed(
    key: str, _provider: Provider, origin: Point, destination: Point
):
    return await providers.fetch_routes_timed(_provider, origin, destination)


async def fetch_routes_timed(provider: Provider, origin: Point, destination: Point):
    key = provider.cache_key
    return await _unless_failed(
        ("routes", key, origin, destination),
        lambda: _fetch_routes_timed(key, provider, origin, destination),
    )


async def fetch_routes(provider: Provider, origin: Point, destination: Point):
    routes, _ = await fetch_routes_timed(provider, origin, destination)
    return routes


_get_edges = st.cache_data(show_spinner=False, persist="disk")(map_matching.get_edges)


async def get_edges(points: Sequence[Point]):
    return await _unless_failed(("edges", tuple(points)), lambda: _get_edges(points))


# Streamlit only notices changes to a cached function's own code, not to what it calls, so the code of the whole module is part of the key, so that e.g. adding a layer refetches the surroundings
_SURROUNDINGS_CODE = hashlib.sha256(
    inspect.getsource(surroundings).encode()
).hexdigest()


@st.cache_data(show_spinner=False, persist="disk")
async def _get_tile(code: str, x: int, y: int, zoom: int):
    return await surroundings.get_tile(x, y, zoom)


async def get_surroundings(routes: Sequence[Sequence[Point]]):
    """Cached per map tile rather than per set of routes, so that routes overlapping ones seen before only fetch the tiles that are new."""
    return await surroundings.get_surroundings(
        routes, lambda x, y, zoom: _get_tile(_SURROUNDINGS_CODE, x, y, zoom)
    )


@st.cache_resource
def _permanent_failures() -> dict[tuple, str]:
    """Call -> the message of an error it got that would only happen again (see `politeness.is_permanent()`), shared across sessions. In memory rather than on disk, so restarting the app tries them again, e.g. after upgrading a provider's plan."""
    return {}


async def _unless_failed(key: tuple, call: Callable[[], Awaitable[T]]) -> T:
    """Returns what `call()` does, unless the same call already failed in a way that would only happen again, in which case it raises that error again without making the request."""
    failures = _permanent_failures()
    if key in failures:
        raise ProviderError(failures[key])
    try:
        return await call()
    except Exception as e:
        if is_permanent(e):
            failures[key] = str(e)
        raise
