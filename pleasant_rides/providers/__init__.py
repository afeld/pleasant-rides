"""Each provider exposes `get_routes(origin, destination) -> list[(label, [(lat, lon), ...])]`.

`origin` and `destination` are dicts with `lat` and `lon` keys.
"""
import asyncio
import os
import re

from . import apple, brouter, cyclemate, google, graphhopper, valhalla

PROVIDERS = {
    "Valhalla": valhalla.get_routes,
    "BRouter": brouter.get_routes,
    "GraphHopper": graphhopper.get_routes,
    "Google Maps": google.get_routes,
    "Cyclemate": cyclemate.get_routes,
    "Apple Maps": apple.get_routes,
}

_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
# e.g. `?key=...` in a request URL that ends up in an exception message
_SECRET_PARAM = re.compile(r"([?&](?:api_?)?key=)[^&\s']+", re.IGNORECASE)


def redact(text):
    """Strip API keys and other secrets from `text`, so they don't end up in the app."""
    for name, value in os.environ.items():
        if name.upper().endswith(_SECRET_SUFFIXES) and value:
            text = text.replace(value, f"<{name}>")
    return _SECRET_PARAM.sub(r"\1<redacted>", text)


async def fetch_routes(name, origin, destination):
    return await PROVIDERS[name](origin, destination)


async def iter_routes(origin, destination, fetch=fetch_routes):
    """Runs every provider concurrently, yielding `(name, routes, error)` as each one finishes.

    `error` is a (redacted) message when the provider failed, e.g. from a missing API key, and `routes` is then None.
    `fetch(name, origin, destination)` defaults to calling the provider directly; pass a cached version to reuse results.
    """

    async def run(name):
        try:
            return name, await fetch(name, origin, destination), None
        except Exception as e:
            return name, None, redact(f"{name}: skipped ({type(e).__name__}: {e})")

    for next_done in asyncio.as_completed([run(name) for name in PROVIDERS]):
        yield await next_done
