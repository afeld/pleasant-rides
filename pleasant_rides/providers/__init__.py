"""Each provider exposes `get_routes(origin, destination) -> list[(label, [(lat, lon), ...])]`.

`origin` and `destination` are dicts with `lat` and `lon` keys.
"""
from . import brouter, cyclemate, google, valhalla

PROVIDERS = {
    "Valhalla": valhalla.get_routes,
    "BRouter": brouter.get_routes,
    "Google Maps": google.get_routes,
    "Cyclemate": cyclemate.get_routes,
}
