"""Getting a route into navigation apps: as a GPX file, which keeps its exact line, or a Google Maps link, which can only approximate it with waypoints."""

import re
from bisect import bisect_left
from itertools import accumulate
from urllib.parse import urlencode

import gpxpy.gpx
from pyproj import Geod

from .models import Point, Route

_GEOD = Geod(ellps="WGS84")
# https://developers.google.com/maps/documentation/urls/get-started#directions-action
MAX_WAYPOINTS = 9
MAX_WAYPOINTS_MOBILE = 3
# where Ride with GPS takes files: https://support.ridewithgps.com/hc/en-us/articles/4419024044827-Upload-Activities-Routes-GPS-Files
RIDE_WITH_GPS_UPLOAD_URL = "https://ridewithgps.com/upload"


def to_gpx(route: Route):
    """The route as a GPX track, rather than a GPX route, which some apps treat as stops to route between on their own."""
    segment = gpxpy.gpx.GPXTrackSegment(
        [gpxpy.gpx.GPXTrackPoint(p.lat, p.lon) for p in route.points]
    )
    track = gpxpy.gpx.GPXTrack(name=f"{route.provider}: {route.label}")
    track.segments.append(segment)
    gpx = gpxpy.gpx.GPX()
    gpx.tracks.append(track)
    return gpx.to_xml()


def gpx_filename(route: Route):
    slug = re.sub(r"[^a-z0-9]+", "-", f"{route.provider} {route.label}".lower())
    return f"{slug.strip('-')}.gpx"


def _waypoints(points: tuple[Point, ...], count: int):
    """Up to `count` of the points, about evenly spaced by distance between the ends, using the route's own points so that they're on its roads."""
    lats = [p.lat for p in points]
    lons = [p.lon for p in points]
    _, _, distances = _GEOD.inv(lons[:-1], lats[:-1], lons[1:], lats[1:])
    along = list(accumulate(distances, initial=0))
    indexes = (
        bisect_left(along, along[-1] * (i + 1) / (count + 1)) for i in range(count)
    )
    # a route with few points can land on the same one twice
    inner = range(1, len(points) - 1)
    return [points[i] for i in dict.fromkeys(indexes) if i in inner]


def _coordinates(point: Point):
    # 5 decimal places is ~1 m, and keeps the URL short
    return f"{round(point.lat, 5)},{round(point.lon, 5)}"


def google_maps_url(route: Route, max_waypoints: int = MAX_WAYPOINTS):
    """A link to bike directions along the route. Google picks its own way between the waypoints, so the closer they are, the closer it follows the route."""
    params = {
        "api": 1,
        "origin": _coordinates(route.points[0]),
        "destination": _coordinates(route.points[-1]),
        "travelmode": "bicycling",
        "dir_action": "navigate",
    }
    waypoints = _waypoints(route.points, max_waypoints)
    if waypoints:
        params["waypoints"] = "|".join(_coordinates(p) for p in waypoints)
    return f"https://www.google.com/maps/dir/?{urlencode(params)}"


def is_mobile(user_agent: str | None):
    return bool(user_agent and re.search(r"Mobi|Android", user_agent))
