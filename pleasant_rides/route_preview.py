"""A street-level preview of the highlighted route on the map: Mapillary's photos along it (see `street_photos`), which you can step through like riding it, with a marker on the map showing where you are."""

from collections.abc import Sequence
from itertools import accumulate

from branca.element import MacroElement
from jinja2 import Template
from pyproj import Geod

from .map import Segment, segment_colors
from .models import Point
from .street_photos import Step

# loaded only when the preview is first opened, since it's a large download
MAPILLARY_JS = "https://unpkg.com/mapillary-js@4.1.2/dist/mapillary.js"
MAPILLARY_CSS = "https://unpkg.com/mapillary-js@4.1.2/dist/mapillary.css"

_GEOD = Geod(ellps="WGS84")
METERS_PER_MILE = 1609.344
# stretches longer than this without a photo are pointed out; steps are 50 m apart, so photos are usually ~50 m apart and up to ~75 m
GAP_M = 150


def route_miles(points: Sequence[Point]):
    return _route_m(points) / METERS_PER_MILE


def _route_m(points: Sequence[Point]):
    return _GEOD.line_length([p.lon for p in points], [p.lat for p in points])


def _gap_mi(meters: float):
    """`meters` in miles if it's long enough to point out, else None."""
    return round(meters / METERS_PER_MILE, 1) if meters > GAP_M else None


def step_data(
    points: Sequence[Point], steps: Sequence[Step], segments: Sequence[Segment]
):
    """What the browser needs for each step, including the color and description of the road segment it's on, and how far it is to the photos before and after it (or the ends of the route) when there's a gap without any."""
    route_m = _route_m(points)
    alongs = [step.along_m for step in steps]
    total = sum(s.length for s in segments)
    # where each segment ends, as a share of the route, since their lengths only roughly add up to the route's (see `map.split_by_lengths()`)
    ends = [length / total for length in accumulate(s.length for s in segments)]
    colors = segment_colors()
    data = []
    i = 0
    for n, step in enumerate(steps):
        share = step.along_m / route_m if route_m else 0
        while i < len(ends) - 1 and ends[i] < share:
            i += 1
        segment = segments[i] if segments else Segment(0, None)
        data.append(
            {
                "id": step.photo_id,
                "lat": round(step.point.lat, 6),
                "lon": round(step.point.lon, 6),
                "along_mi": round(step.along_m / METERS_PER_MILE, 2),
                "bearing": round(step.bearing),
                "pano": step.is_pano,
                "compass": round(step.compass_angle),
                "color": None if segment.score is None else colors(segment.score),
                "info": segment.description,
                "gap_behind_mi": _gap_mi(step.along_m - (alongs[n - 1] if n else 0)),
                "gap_ahead_mi": _gap_mi(
                    (alongs[n + 1] if n + 1 < len(steps) else route_m) - step.along_m
                ),
            }
        )
    return data


class RoutePreview(MacroElement):
    """A "Preview route" button on the map that opens MapillaryJS in a panel, with buttons, arrow keys, and a slider to step along the route. Clicking the route on the map jumps to the nearest step."""

    _template = Template("""
        {% macro header(this, kwargs) %}
        <style>
            .route-preview {
                position: absolute; z-index: 1001; left: 10px; right: 10px; bottom: 30px; height: 60%;
                display: none; flex-direction: column; overflow: hidden;
                background: #fff; color: #222; border-radius: 8px; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.35);
                font: 14px/1.4 system-ui, sans-serif;
            }
            @media (min-width: 700px) { .route-preview { right: auto; width: 50%; } }
            .route-preview.open { display: flex; }
            .route-preview-viewer { flex: 1; position: relative; min-height: 0; background: #eee; }
            .route-preview-info { padding: 6px 10px 0; }
            .route-preview-gap { color: #8a4b00; font-weight: 600; }
            .route-preview-swatch { display: inline-block; width: 12px; height: 12px; margin-right: 6px; border-radius: 2px; vertical-align: -1px; }
            .route-preview-controls { display: flex; align-items: center; gap: 8px; padding: 6px 10px 10px; }
            .route-preview-controls button { min-width: 44px; min-height: 44px; font-size: 18px; border: 1px solid #ccc; border-radius: 6px; background: #fff; cursor: pointer; }
            .route-preview-controls button:disabled { opacity: 0.4; cursor: default; }
            .route-preview-controls input { flex: 1; min-height: 44px; }
            .route-preview-open { font: 14px system-ui, sans-serif; padding: 8px 10px; min-height: 44px; background: #fff; border: 2px solid rgba(0, 0, 0, 0.2); border-radius: 4px; cursor: pointer; }
            .route-preview-marker { font-size: 26px; line-height: 28px; text-align: center; color: #111; text-shadow: 0 0 3px #fff, 0 0 3px #fff; }
        </style>
        {% endmacro %}

        {% macro script(this, kwargs) %}
        (function (map) {
            var steps = {{ this.steps|tojson }};
            var routeMi = {{ this.route_mi|tojson }};
            var token = {{ this.token|tojson }};
            var index = 0, viewer = null, loading = null, pending = null;

            var panel = L.DomUtil.create("div", "route-preview", map.getContainer());
            panel.setAttribute("role", "region");
            panel.setAttribute("aria-label", "Street-level preview of the route");
            panel.tabIndex = -1;
            panel.innerHTML =
                '<div class="route-preview-viewer"></div>' +
                '<div class="route-preview-info" aria-live="polite"></div>' +
                '<div class="route-preview-controls">' +
                '<button type="button" data-step="-1" aria-label="Step back">&#9664;</button>' +
                '<input type="range" min="0" max="' + (steps.length - 1) + '" value="0" aria-label="Position along the route">' +
                '<button type="button" data-step="1" aria-label="Step forward">&#9654;</button>' +
                '<button type="button" data-close aria-label="Close the preview">&#10005;</button>' +
                "</div>";
            L.DomEvent.disableClickPropagation(panel);
            L.DomEvent.disableScrollPropagation(panel);
            var viewerEl = panel.querySelector(".route-preview-viewer");
            var info = panel.querySelector(".route-preview-info");
            var slider = panel.querySelector("input");
            var back = panel.querySelector('[data-step="-1"]');
            var forward = panel.querySelector('[data-step="1"]');

            // an arrow pointing which way the route goes
            var marker = L.marker([0, 0], {
                icon: L.divIcon({ className: "route-preview-marker", html: '<div>&#10148;</div>', iconSize: [28, 28] }),
                interactive: false,
                keyboard: false,
                zIndexOffset: 1000,
            });

            function load() {
                if (!loading) {
                    loading = new Promise(function (resolve, reject) {
                        var css = document.createElement("link");
                        css.rel = "stylesheet";
                        css.href = {{ this.css_url|tojson }};
                        document.head.appendChild(css);
                        var js = document.createElement("script");
                        js.src = {{ this.js_url|tojson }};
                        js.onload = resolve;
                        js.onerror = reject;
                        document.head.appendChild(js);
                    });
                }
                return loading;
            }

            // a 360° photo's center faces its compass angle, so turn it to face along the route
            function faceAlongRoute(event) {
                var step = steps[index];
                if (step.pano && event.image && event.image.id === step.id) {
                    viewer.setCenter([((((step.bearing - step.compass) / 360 + 0.5) % 1) + 1) % 1, 0.5]);
                }
            }

            // keeps the marker in the middle of the part of the map the panel doesn't cover (beside it on wide screens, above it on narrow ones), away from the legend and controls at the edges
            function keepVisible(latlng) {
                var p = panel.getBoundingClientRect(), c = map.getContainer().getBoundingClientRect();
                var beside = p.width < c.width * 0.8;
                var left = beside ? p.right - c.left : 0, bottom = beside ? 0 : c.bottom - p.top;
                var marginX = (c.width - left) / 4, marginY = (c.height - bottom) / 4;
                map.panInside(latlng, {
                    paddingTopLeft: [left + marginX, marginY],
                    paddingBottomRight: [marginX, bottom + marginY],
                    // animated pans fall behind when stepping quickly
                    animate: false,
                });
            }

            // stretches without photos, which stepping jumps over
            function gapNote(step) {
                var notes = [];
                if (step.gap_behind_mi) notes.push("No photos for the " + (index === 0 ? "first " : "") + step.gap_behind_mi + " mi" + (index === 0 ? "" : " before here"));
                if (step.gap_ahead_mi) notes.push("No photos for the " + (index === steps.length - 1 ? "last " : "next ") + step.gap_ahead_mi + " mi");
                return notes.length ? '<div class="route-preview-gap">' + notes.join("; ") + "</div>" : "";
            }

            function label(button, action, gapMi) {
                var text = gapMi && !button.disabled ? action + ", skipping " + gapMi + " mi without photos" : action;
                button.setAttribute("aria-label", text);
                button.title = text;
            }

            function show(i) {
                index = Math.max(0, Math.min(steps.length - 1, i));
                var step = steps[index];
                slider.value = index;
                back.disabled = index === 0;
                forward.disabled = index === steps.length - 1;
                var swatch = step.color ? '<span class="route-preview-swatch" style="background:' + step.color + '"></span>' : "";
                info.innerHTML = swatch + (step.info || "") + " &middot; mile " + step.along_mi.toFixed(1) + " of " + routeMi.toFixed(1) + gapNote(step);
                label(back, "Step back", step.gap_behind_mi);
                label(forward, "Step forward", step.gap_ahead_mi);
                marker.setLatLng([step.lat, step.lon]).addTo(map);
                marker.getElement().firstChild.style.transform = "rotate(" + (step.bearing - 90) + "deg)";
                keepVisible(marker.getLatLng());
                // only once stepping pauses, so holding an arrow key or dragging the slider doesn't send Mapillary a burst of requests
                clearTimeout(pending);
                pending = setTimeout(showPhoto, viewer ? {{ this.settle_ms }} : 0);
            }

            function showPhoto() {
                var step = steps[index];
                load().then(function () {
                    if (!viewer) {
                        viewer = new mapillary.Viewer({
                            accessToken: token,
                            container: viewerEl,
                            imageId: step.id,
                            // stepping follows our route rather than the photographer's, so the viewer's own navigation is off
                            component: { cover: false, sequence: false, direction: false, keyboard: false },
                        });
                        viewer.on("image", faceAlongRoute);
                    } else {
                        viewer.moveTo(step.id).catch(function () {});
                    }
                });
            }

            function open(i) {
                panel.classList.add("open");
                // close enough to see the street the photo is on
                if (map.getZoom() < {{ this.zoom }}) map.setZoom({{ this.zoom }}, { animate: false });
                show(i);
                if (viewer) viewer.resize();
                panel.focus();
            }

            function close() {
                panel.classList.remove("open");
                marker.remove();
            }

            panel.addEventListener("click", function (e) {
                var button = e.target.closest("button");
                if (!button) return;
                if (button.hasAttribute("data-close")) close();
                else show(index + Number(button.dataset.step));
            });
            slider.addEventListener("input", function () { show(Number(slider.value)); });
            panel.addEventListener("keydown", function (e) {
                if (e.target === slider) return;
                if (e.key === "ArrowLeft") { show(index - 1); e.preventDefault(); }
                else if (e.key === "ArrowRight") { show(index + 1); e.preventDefault(); }
                else if (e.key === "Escape") close();
            });

            var Button = L.Control.extend({
                onAdd: function () {
                    var button = L.DomUtil.create("button", "route-preview-open");
                    button.type = "button";
                    button.textContent = "Preview route";
                    L.DomEvent.disableClickPropagation(button);
                    button.addEventListener("click", function () { open(index); });
                    return button;
                },
            });
            new Button({ position: "topleft" }).addTo(map);
            // once the page has loaded and the map has finished its animated zoom to fit the routes, since Leaflet ignores zooming (as open() does) during one
            function openWhenSettled() {
                if (map._animatingZoom) map.once("zoomend", function () { setTimeout(openWhenSettled); });
                else open(0);
            }
            if ({{ this.open|tojson }}) window.addEventListener("load", openWhenSettled);

            map.on("resize", function () {
                if (panel.classList.contains("open")) keepVisible(marker.getLatLng());
            });

            // clicking near the route jumps to the closest step there
            map.on("click", function (e) {
                var point = map.latLngToContainerPoint(e.latlng);
                var best = -1, bestDistance = {{ this.tolerance }};
                steps.forEach(function (step, i) {
                    var d = point.distanceTo(map.latLngToContainerPoint([step.lat, step.lon]));
                    if (d < bestDistance) { best = i; bestDistance = d; }
                });
                if (best >= 0) open(best);
            });
        })({{ this._parent.get_name() }});
        {% endmacro %}
    """)

    def __init__(
        self,
        steps: list[dict],
        token: str,
        route_mi: float,
        open: bool = False,
        tolerance: int = 30,
    ):
        """`open` opens the preview at the start of the route as soon as the map loads."""
        super().__init__()
        self._name = "RoutePreview"
        self.open = open
        self.steps = steps
        self.token = token
        self.route_mi = route_mi
        self.js_url = MAPILLARY_JS
        self.css_url = MAPILLARY_CSS
        # how close (in pixels) a click needs to be to a step
        self.tolerance = tolerance
        self.zoom = 16
        self.settle_ms = 300
