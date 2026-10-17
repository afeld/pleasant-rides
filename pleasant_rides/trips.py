"""Sample trips covering different kinds of riding, which the Benchmark page compares providers on and the planner offers as presets."""

from .models import Point

# name -> (origin, destination)
TRIPS = {
    "Long: Brooklyn→Beacon": (Point(40.6782, -73.9442), Point(41.5048, -73.9696)),
    "Urban: Park Slope→UWS": (Point(40.6710, -73.9814), Point(40.7870, -73.9754)),
    "Rural: Beacon→Cold Spring": (
        Point(41.5048, -73.9696),
        Point(41.4201, -73.9546),
    ),
    "Suburban: Hoboken→Montclair": (
        Point(40.7440, -74.0324),
        Point(40.8259, -74.2090),
    ),
}


def short(trip: str):
    """e.g. "Long" from "Long: Brooklyn→Beacon"."""
    return trip.split(":")[0]
