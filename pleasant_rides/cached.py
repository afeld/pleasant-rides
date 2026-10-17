"""Cached versions of the API calls, shared by the app's pages, so reruns don't hit the providers again.

They're persisted to disk, so they also survive restarting the app; use "Clear cache" from the app's ⋮ menu to refetch.
Failures aren't cached (exceptions propagate), so they get retried on the next run, except ones that would only happen again (see `_unless_failed()`). Scores aren't cached, only the data they're computed from, so that changes to the scoring take effect.
"""

import hashlib
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

import streamlit as st

from . import map_matching, overture, providers, surroundings
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


# Streamlit only notices changes to a cached function's own code, not to what it calls, so the code of the module that reads from Overture is part of the key, so that e.g. reading another column refetches the tiles. Changes to `surroundings` (which features count, and how routes are measured against them) don't need a refetch.
_OVERTURE_CODE = hashlib.sha256(inspect.getsource(overture).encode()).hexdigest()


# not on disk, so that a new release is picked up after restarting the app
@st.cache_data(show_spinner=False, ttl="1d")
def _latest_release():
    return overture.latest_release()


@st.cache_data(show_spinner=False, persist="disk")
async def _get_tile(code: str, release: str, x: int, y: int, zoom: int):
    return await overture.get_tile(release, x, y, zoom)


@st.cache_resource
def _loaded_tiles() -> dict[tuple, surroundings.Tables]:
    """Tiles already loaded from the disk cache, kept in memory as they are, since `st.cache_data` unpickles a fresh copy on every hit, which adds up to around a second per rerun for a city's worth. They're only read, never changed, so sharing them is safe."""
    return {}


async def _tile(release: str, x: int, y: int, zoom: int):
    key = (_OVERTURE_CODE, release, x, y, zoom)
    loaded = _loaded_tiles()
    if key not in loaded:
        loaded[key] = await _get_tile(*key)
    return loaded[key]


async def get_surroundings(routes: Sequence[Sequence[Point]]):
    """Cached per map tile of Overture's latest release rather than per set of routes, so that routes overlapping ones seen before only fetch the tiles that are new."""
    release = _latest_release()
    return await surroundings.get_surroundings(
        routes, lambda x, y, zoom: _tile(release, x, y, zoom)
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
