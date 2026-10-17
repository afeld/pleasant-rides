"""Cached versions of the API calls, shared by the app's pages, so reruns don't hit the providers again.

They're persisted to disk, so they also survive restarting the app; use "Clear cache" from the app's ⋮ menu to refetch.
Failures aren't cached (exceptions propagate), so they get retried on the next run. Scores aren't cached, only the data
they're computed from, so that changes to the scoring take effect.
"""

import streamlit as st

from . import map_matching, providers, surroundings
from .geocode import geocode_place
from .models import Point
from .providers.base import Provider

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
    return await _fetch_routes_timed(provider.cache_key, provider, origin, destination)


async def fetch_routes(provider: Provider, origin: Point, destination: Point):
    routes, _ = await fetch_routes_timed(provider, origin, destination)
    return routes


get_edges = st.cache_data(show_spinner=False, persist="disk")(map_matching.get_edges)
get_surroundings = st.cache_data(show_spinner=False, persist="disk")(
    surroundings.get_surroundings
)
