"""Cached versions of the API calls, shared by the app's pages, so reruns don't hit the providers again.

Failures aren't cached (exceptions propagate), so they get retried on the next run.
"""

import streamlit as st

from . import providers, scoring, surroundings
from .geocode import geocode_place
from .models import Point
from .providers.base import Provider

geocode = st.cache_data(show_spinner="Geocoding…")(geocode_place)


# `_provider` is left out of the cache key (Streamlit skips parameters starting with an underscore); `key` stands in
# for it, so that each provider and settings are cached separately
@st.cache_data(show_spinner=False)
async def _fetch_routes(
    key: str, _provider: Provider, origin: Point, destination: Point
):
    return await providers.fetch_routes(_provider, origin, destination)


async def fetch_routes(provider: Provider, origin: Point, destination: Point):
    return await _fetch_routes(provider.cache_key, provider, origin, destination)


get_edges = st.cache_data(show_spinner=False)(scoring.get_edges)
get_surroundings = st.cache_data(show_spinner=False)(surroundings.get_surroundings)
