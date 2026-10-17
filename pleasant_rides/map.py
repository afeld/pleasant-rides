import folium
from branca.element import MacroElement
from folium.elements import JSCSSMixin
from jinja2 import Template


class OpenFreeMapLayer(JSCSSMixin, MacroElement):
    """OpenFreeMap vector base map, rendered through MapLibre GL in Leaflet."""

    _template = Template("""
        {% macro script(this, kwargs) %}
        L.maplibreGL({
            style: {{ this.style_url|tojson }},
            attribution: {{ this.attribution|tojson }},
            // without a tile layer, Leaflet has no max zoom, which breaks fit_bounds()
            maxZoom: 19,
        }).addTo({{ this._parent.get_name() }});
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

    def __init__(self, style="positron"):
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
        {% macro script(this, kwargs) %}
        (function (map) {
            var tooltip = L.tooltip({ direction: "top", offset: [0, -8] });
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

    def __init__(self, delay_ms=400, tolerance=8):
        super().__init__()
        self._name = "RouteTooltip"
        self.delay_ms = delay_ms
        # how close (in pixels) the cursor needs to be to a route
        self.tolerance = tolerance


COLORS = ["#E63946", "#1D3557", "#2A9D8F", "#F4A261", "#457B9D", "#8338EC"]


def build_map(provider_routes):
    """`provider_routes` maps provider name -> list of (label, points). One toggleable layer per provider."""
    all_points = [
        pt
        for routes in provider_routes.values()
        for _, points in routes
        for pt in points
    ]
    if not all_points:
        raise ValueError("no routes to map")

    m = folium.Map(location=all_points[0], zoom_start=14, tiles=None)
    OpenFreeMapLayer().add_to(m)

    for idx, (provider, routes) in enumerate(provider_routes.items()):
        color = COLORS[idx % len(COLORS)]
        layer = folium.FeatureGroup(
            # Leaflet's layer control renders names as HTML, so add a color swatch
            name=f'<span style="color:{color}; font-size:1.2em">&#9632;</span> {provider}'
        )
        for label, points in routes:
            line = folium.PolyLine(points, color=color, weight=5, opacity=0.8)
            # folium drops unknown options in the constructor; RouteTooltip reads this one
            line.options["routeLabel"] = f'<span style="color:{color}">&#9632;</span> {provider}: {label}'
            line.add_to(layer)
        layer.add_to(m)

    first = next(iter(provider_routes.values()))[0][1]
    folium.Marker(first[0], tooltip="Start", icon=folium.Icon(color="green")).add_to(m)
    folium.Marker(first[-1], tooltip="End", icon=folium.Icon(color="red")).add_to(m)

    lats = [p[0] for p in all_points]
    lons = [p[1] for p in all_points]
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    folium.LayerControl(collapsed=False).add_to(m)
    RouteTooltip().add_to(m)
    return m
