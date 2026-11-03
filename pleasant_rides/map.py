from collections.abc import Sequence
from typing import NamedTuple
from itertools import accumulate, pairwise

import folium
from branca.colormap import LinearColormap
from branca.element import MacroElement
from folium.elements import JSCSSMixin
from jinja2 import Template
from pyproj import Geod

from .models import Point, Route


class OpenFreeMapLayer(JSCSSMixin, MacroElement):
    """OpenFreeMap vector base map, rendered through MapLibre GL in Leaflet.

    It's drawn as two layers from the same style: everything but the labels (street names, places, etc.) below the routes, and the labels above them, so the routes don't cover them up.
    """

    _template = Template("""
        {% macro script(this, kwargs) %}
        (function (map) {
            // above the routes (Leaflet's overlay pane is 400), but below the start/end markers (600)
            var labelsPane = map.createPane("labels");
            labelsPane.style.zIndex = 450;
            // so the routes' tooltips still work through it
            labelsPane.style.pointerEvents = "none";

            // a wide white halo, so the labels stay readable on top of the routes
            function withHalo(layer) {
                if (!layer.layout || !layer.layout["text-field"]) return layer;
                return Object.assign({}, layer, {
                    paint: Object.assign({}, layer.paint, {
                        "text-halo-color": "rgba(255, 255, 255, 0.9)",
                        "text-halo-width": 2,
                        "text-halo-blur": 0.5,
                    }),
                });
            }

            function addLayer(options, keepLayer, transformLayer) {
                var layer = L.maplibreGL(Object.assign({
                    // empty until the real style, filtered by setStyle() below, loads
                    style: { version: 8, sources: {}, layers: [] },
                    // without a tile layer, Leaflet has no max zoom, which breaks fit_bounds()
                    maxZoom: 19,
                }, options)).addTo(map);
                layer.getMaplibreMap().setStyle({{ this.style_url|tojson }}, {
                    transformStyle: function (previous, style) {
                        var layers = style.layers.filter(keepLayer);
                        return Object.assign({}, style, { layers: transformLayer ? layers.map(transformLayer) : layers });
                    },
                });
            }

            // the layers start out with an empty style, so they don't have an attribution yet when added
            map.attributionControl.addAttribution({{ this.attribution|tojson }});
            addLayer({}, function (l) { return l.type !== "symbol"; });
            addLayer({ pane: "labels" }, function (l) { return l.type === "symbol"; }, withHalo);
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    default_js = [
        ("maplibre-gl", "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"),
        (
            "maplibre-gl-leaflet",
            "https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.1.4/leaflet-maplibre-gl.js",
        ),
    ]
    default_css = [
        (
            "maplibre-gl-css",
            "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css",
        ),
    ]

    def __init__(self, style: str = "positron"):
        super().__init__()
        self._name = "OpenFreeMapLayer"
        self.style_url = f"https://tiles.openfreemap.org/styles/{style}"
        self.attribution = (
            '<a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> '
            '<a href="https://www.openmaptiles.org/" target="_blank">&copy; OpenMapTiles</a> '
            'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank">OpenStreetMap</a>'
        )


class RouteTooltip(MacroElement):
    """Once the mouse rests on the map, shows one tooltip listing every visible route near the cursor.

    Leaflet's own tooltips only cover the topmost line, which hides routes that overlap.
    """

    _template = Template("""
        {% macro header(this, kwargs) %}
        <style>
            /* larger than Leaflet's default 12px, so it's easy to read */
            .route-tooltip { font-size: {{ this.font_size_px }}px; }
        </style>
        {% endmacro %}

        {% macro script(this, kwargs) %}
        (function (map) {
            var tooltip = L.tooltip({ direction: "top", offset: [0, -8], className: "route-tooltip" });
            var timer = null;

            function routesNear(latlng) {
                var point = map.latLngToLayerPoint(latlng);
                var labels = [];
                // layers unchecked in the layer control aren't on the map, so they're skipped
                map.eachLayer(function (layer) {
                    if (!(layer instanceof L.Polyline) || !layer.options.routeLabel) return;
                    var pts = layer.getLatLngs().map(function (ll) { return map.latLngToLayerPoint(ll); });
                    for (var i = 1; i < pts.length; i++) {
                        if (L.LineUtil.pointToSegmentDistance(point, pts[i - 1], pts[i]) <= {{ this.tolerance }}) {
                            labels.push(layer.options.routeLabel);
                            return;
                        }
                    }
                });
                return labels;
            }

            function hide() {
                clearTimeout(timer);
                map.closeTooltip(tooltip);
            }

            map.on("mousemove", function (e) {
                hide();
                timer = setTimeout(function () {
                    var labels = routesNear(e.latlng);
                    if (labels.length) {
                        tooltip.setLatLng(e.latlng).setContent(labels.join("<br>"));
                        map.openTooltip(tooltip);
                    }
                }, {{ this.delay_ms }});
            });
            map.on("mouseout movestart zoomstart", hide);
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    def __init__(self, delay_ms: int = 400, tolerance: int = 8, font_size_px: int = 15):
        super().__init__()
        self._name = "RouteTooltip"
        self.delay_ms = delay_ms
        self.font_size_px = font_size_px
        # how close (in pixels) the cursor needs to be to a route
        self.tolerance = tolerance


COLORS = ["#E63946", "#1D3557", "#2A9D8F", "#F4A261", "#457B9D", "#8338EC"]


def segment_colors():
    """Segment score -> color, which is also the map's legend for them, so there's a new one per map."""
    # red to blue (ColorBrewer's RdYlBu), rather than red to green, since it's color-blind safe
    return LinearColormap(
        ["#d7191c", "#fdae61", "#ffffbf", "#abd9e9", "#2c7bb6"],
        vmin=0,
        vmax=100,
        caption="Segment score: traffic, speed, lanes, grade, surface, and rideability",
    )


class Segment(NamedTuple):
    """A road segment along a route."""

    # in any unit, since only their proportions are used
    length: float
    # 0-100, or None if it isn't scored
    score: float | None
    # what it's like, e.g. "secondary road, 2 lanes, protected bike lane, paved"
    description: str = ""


def build_map(
    routes: list[Route],
    highlight: Route | None = None,
    segments: Sequence[Segment] | None = None,
):
    """Maps a list of `Route`s, with one toggleable layer per provider, in the order they first appear.

    `highlight` is an optional `Route` to draw on top of the others, which are faded, and zoom to. If `segments` (its road segments, in order) are given, it's colored by their scores.
    """
    all_points = [pt for route in routes for pt in route.points]
    if not all_points:
        raise ValueError("no routes to map")

    m = folium.Map(location=all_points[0], zoom_start=14, tiles=None)
    OpenFreeMapLayer().add_to(m)

    highlight_color = None
    for idx, (provider, provider_routes) in enumerate(_by_provider(routes).items()):
        color = COLORS[idx % len(COLORS)]
        _provider_layer(provider, provider_routes, color, faded=bool(highlight)).add_to(
            m
        )
        if highlight and any(r.id == highlight.id for r in provider_routes):
            highlight_color = color

    _add_endpoints(m, routes[0])
    if highlight and highlight_color:
        _add_highlight(m, highlight, highlight_color, segments)
        _fit(m, highlight.points)
    else:
        _fit(m, all_points)
    folium.LayerControl(collapsed=False).add_to(m)
    RouteTooltip().add_to(m)
    return m


def _by_provider(routes: list[Route]):
    """Provider name -> its routes, in the order the providers first appear."""
    provider_routes: dict[str, list[Route]] = {}
    for route in routes:
        provider_routes.setdefault(route.provider, []).append(route)
    return provider_routes


def _provider_layer(provider: str, routes: list[Route], color: str, faded: bool):
    layer = folium.FeatureGroup(
        # Leaflet's layer control renders names as HTML, so add a color swatch
        name=f'<span style="color:{color}; font-size:1.2em">&#9632;</span> {provider}'
    )
    for route in routes:
        line = folium.PolyLine(
            route.points, color=color, weight=5, opacity=0.3 if faded else 0.8
        )
        # folium drops unknown options in the constructor; RouteTooltip reads this one
        line.options["routeLabel"] = (
            f'<span style="color:{color}">&#9632;</span> {provider}: {route.label}'
        )
        line.add_to(layer)
    return layer


def _add_endpoints(m: folium.Map, route: Route):
    folium.Marker(
        route.points[0], tooltip="Start", icon=folium.Icon(color="green")
    ).add_to(m)
    folium.Marker(
        route.points[-1], tooltip="End", icon=folium.Icon(color="red")
    ).add_to(m)


def _add_highlight(
    m: folium.Map, route: Route, color: str, segments: Sequence[Segment] | None
):
    # in its own group, outside the layer control, so it's drawn above every provider's layer
    overlay = folium.FeatureGroup(control=False)
    folium.PolyLine(route.points, color="white", weight=11, opacity=1).add_to(overlay)
    if segments:
        colors = segment_colors()
        pieces = split_by_lengths(route.points, [s.length for s in segments])
        for piece, segment in zip(pieces, segments):
            folium.PolyLine(
                piece,
                color=color if segment.score is None else colors(segment.score),
                weight=7,
                opacity=1,
            ).add_to(overlay)
        colors.add_to(m)
    else:
        folium.PolyLine(route.points, color=color, weight=7, opacity=1).add_to(overlay)
    overlay.add_to(m)


_GEOD = Geod(ellps="WGS84")


def split_by_lengths(points: Sequence[Point], lengths: Sequence[float]):
    """`points` cut into consecutive pieces in proportion to `lengths`, each starting where the last one ended. Map-matched road segments come with their lengths but not their shapes, and add up to about the route's length, so this lines them up with the route."""
    gaps = [_GEOD.inv(a.lon, a.lat, b.lon, b.lat)[2] for a, b in pairwise(points)]
    total = sum(lengths)
    scale = sum(gaps) / total if total else 0
    # how far along the route each piece ends, other than the last
    cuts = list(accumulate(length * scale for length in lengths))[:-1]
    pieces: list[list[Point]] = []
    piece = [points[0]]
    travelled = 0.0
    i = 0
    for cut in cuts:
        # move to the gap between points that the cut falls in
        while i < len(gaps) - 1 and travelled + gaps[i] < cut:
            travelled += gaps[i]
            i += 1
            piece.append(points[i])
        a, b = points[i], points[i + 1]
        frac = min((cut - travelled) / gaps[i], 1) if gaps[i] else 0
        cut_point = Point(
            a.lat + (b.lat - a.lat) * frac, a.lon + (b.lon - a.lon) * frac
        )
        piece.append(cut_point)
        pieces.append(piece)
        piece = [cut_point]
    piece.extend(points[i + 1 :])
    pieces.append(piece)
    return pieces


def _fit(m: folium.Map, points: Sequence[Point]):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
