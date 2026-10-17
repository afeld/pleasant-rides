"""Each provider exposes `get_routes(origin, destination) -> list[(label, [(lat, lon), ...])]`.

`origin` and `destination` are dicts with `lat` and `lon` keys.
"""
import os
import re

from . import brouter, cyclemate, google, graphhopper, valhalla

PROVIDERS = {
    "Valhalla": valhalla.get_routes,
    "BRouter": brouter.get_routes,
    "GraphHopper": graphhopper.get_routes,
    "Google Maps": google.get_routes,
    "Cyclemate": cyclemate.get_routes,
}

_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
# e.g. `?key=...` in a request URL that ends up in an exception message
_SECRET_PARAM = re.compile(r"([?&](?:api_?)?key=)[^&\s']+", re.IGNORECASE)


def redact(text):
    """Strip API keys and other secrets from `text`, so they don't end up in notebook output."""
    for name, value in os.environ.items():
        if name.upper().endswith(_SECRET_SUFFIXES) and value:
            text = text.replace(value, f"<{name}>")
    return _SECRET_PARAM.sub(r"\1<redacted>", text)


def get_all_routes(origin, destination):
    """Returns provider name -> routes, skipping (and reporting) providers that fail."""
    provider_routes = {}
    for name, get_routes in PROVIDERS.items():
        try:
            provider_routes[name] = get_routes(origin, destination)
        except Exception as e:  # e.g. missing API key
            print(redact(f"{name}: skipped ({type(e).__name__}: {e})"))
    return provider_routes
