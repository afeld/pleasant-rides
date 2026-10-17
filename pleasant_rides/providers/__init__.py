"""Routing providers, each a `Provider` with `async get_routes(origin, destination) -> [Route, ...]`."""

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable

from ..models import Point, Route
from .apple import Apple
from .base import Provider
from .brouter import BRouter
from .cyclemate import Cyclemate
from .google import Google
from .graphhopper import GraphHopper
from .valhalla import Valhalla

# by name, in the order they're shown
PROVIDERS = {
    provider.name: provider
    for provider in [
        Valhalla(),
        BRouter(),
        GraphHopper(),
        Google(),
        Cyclemate(),
        Apple(),
    ]
}

_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
# e.g. `?key=...` in a request URL that ends up in an exception message
_SECRET_PARAM = re.compile(r"([?&](?:api_?)?key=)[^&\s']+", re.IGNORECASE)


def redact(text: str):
    """Strip API keys and other secrets from `text`, so they don't end up in the app."""
    for name, value in os.environ.items():
        if name.upper().endswith(_SECRET_SUFFIXES) and value:
            text = text.replace(value, f"<{name}>")
    return _SECRET_PARAM.sub(r"\1<redacted>", text)


async def fetch_routes(provider: Provider, origin: Point, destination: Point):
    return await provider.get_routes(origin, destination)


async def fetch_routes_timed(provider: Provider, origin: Point, destination: Point):
    """Returns the routes and how many seconds the provider took to return them."""
    started = time.perf_counter()
    routes = await provider.get_routes(origin, destination)
    return routes, time.perf_counter() - started


async def iter_routes(
    origin: Point,
    destination: Point,
    fetch: Callable[[Provider, Point, Point], Awaitable[list[Route]]] = fetch_routes,
):
    """Runs every provider concurrently, yielding `(name, [Route, ...], error)` as each one finishes.

    `error` is a (redacted) message when the provider failed, e.g. from a missing API key, and `routes` is then None.
    `fetch(provider, origin, destination)` defaults to calling the provider directly; pass a cached version to reuse results.
    """

    async def run(name: str):
        try:
            return name, await fetch(PROVIDERS[name], origin, destination), None
        except Exception as e:
            return name, None, redact(f"{name}: skipped ({type(e).__name__}: {e})")

    for next_done in asyncio.as_completed([run(name) for name in PROVIDERS]):
        yield await next_done
