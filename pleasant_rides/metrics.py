"""The kinds of metric a route is measured by, and the route data they measure."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pyproj import Geod

from .edges import total_km, total_miles
from .map_matching import Edge
from .models import Point
from .surroundings import Surroundings


@dataclass(frozen=True)
class Ride:
    """Everything the metrics measure about a route."""

    points: Sequence[Point]
    edges: list[Edge]
    # None if they couldn't be fetched, in which case the metrics that use them are left out
    surroundings: Surroundings | None


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    help: str = ""
    # how much it counts toward the overall score; 0 for metrics that are only shown
    weight: float = 0
    # how the app displays it: "percent", or a printf-style format
    format: str = "%.0f"

    def measure(self, ride: Ride) -> float | None:
        """The value shown for a route, or None if it doesn't apply."""
        raise NotImplementedError

    def score(self, value: float):
        """`value` as 0-1, higher being better."""
        return value

    def score_edge(self, edge: Edge) -> float | None:
        """A single road segment's credit (0-1), or None if this metric doesn't apply to segments on their own (like turns, or surroundings) or to this one."""
        return None

    @property
    def scoring_rule(self) -> str:
        """How `score()` turns the value into credit, for explaining it in the app."""
        return "In proportion to the share" if self.weight else "Not scored, only shown"


# keyword-only, so these fields can be required even though Metric's later ones have defaults
@dataclass(frozen=True, kw_only=True)
class Total(Metric):
    """A number for the whole route, such as its distance."""

    compute: Callable[[list[Edge]], float]

    def measure(self, ride: Ride):
        return self.compute(ride.edges)


@dataclass(frozen=True, kw_only=True)
class Share(Metric):
    """The share (0-1) of the route's distance that meets `condition`, out of the edges that `of` selects."""

    condition: Callable[[Edge], bool]
    of: Callable[[list[Edge]], list[Edge]] = lambda edges: edges
    format: str = field(default="percent", init=False)

    def measure(self, ride: Ride):
        edges = self.of(ride.edges)
        total = total_km(edges)
        return (
            total_km([e for e in edges if self.condition(e)]) / total if total else None
        )

    def score_edge(self, edge: Edge):
        return float(self.condition(edge)) if self.of([edge]) else None


@dataclass(frozen=True, kw_only=True)
class PerMile(Metric):
    """How many times something happens per mile, where fewer is better."""

    count: Callable[[list[Edge]], int]
    # the rate that scores 0.5
    half_score: float = 1
    format: str = "%.1f"

    def measure(self, ride: Ride):
        miles = total_miles(ride.edges)
        return self.count(ride.edges) / miles if miles else None

    def score(self, value: float):
        return self.half_score / (self.half_score + value)

    @property
    def scoring_rule(self):
        return f"Half credit at {self.half_score:g}/mi; fewer is better"


@dataclass(frozen=True, kw_only=True)
class Near(Metric):
    """The share (0-1) of the route's distance within `distance` meters of a feature in a `layer` of its surroundings."""

    layer: str
    distance: float
    format: str = field(default="percent", init=False)

    def measure(self, ride: Ride):
        if ride.surroundings is None:
            return None
        return ride.surroundings.share_near(ride.points, self.layer, self.distance)


@dataclass(frozen=True, kw_only=True)
class PassesPerMile(Metric):
    """How many features in a `layer` of the route's surroundings it passes within `distance` meters of, per mile, where more is better."""

    layer: str
    distance: float
    # the rate that scores 0.5
    half_score: float = 1
    format: str = "%.1f"

    def measure(self, ride: Ride):
        miles = total_miles(ride.edges)
        if ride.surroundings is None or not miles:
            return None
        return (
            ride.surroundings.count_near(ride.points, self.layer, self.distance) / miles
        )

    def score(self, value: float):
        return value / (self.half_score + value)

    @property
    def scoring_rule(self):
        return f"Half credit at {self.half_score:g}/mi; more is better"


@dataclass(frozen=True, kw_only=True)
class Away(Near):
    """The share (0-1) of the route's distance that's *not* within `distance` meters of a feature in a `layer` of its surroundings."""

    def measure(self, ride: Ride):
        near = super().measure(ride)
        return None if near is None else 1 - near


@dataclass(frozen=True, kw_only=True)
class LowerIsBetter(Metric):
    """A value where lower is better, scored by how far it is above `best`."""

    # the value at or below which it scores 1
    best: float
    # the value that scores 0.5
    half_score: float
    format: str = "%.1f"

    def score(self, value: float):
        half = self.half_score - self.best
        return half / (half + max(value - self.best, 0))

    @property
    def scoring_rule(self):
        return f"Full credit at {self.best:g} or less; half at {self.half_score:g}"


@dataclass(frozen=True, kw_only=True)
class Average(LowerIsBetter):
    """The distance-weighted average of `value` over the edges that `of` selects, where lower is better."""

    value: Callable[[Edge], float]
    of: Callable[[list[Edge]], list[Edge]] = lambda edges: edges

    def measure(self, ride: Ride):
        edges = self.of(ride.edges)
        km = total_km(edges)
        return sum(self.value(e) * e["length"] for e in edges) / km if km else None

    def score_edge(self, edge: Edge):
        return self.score(self.value(edge)) if self.of([edge]) else None


_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True, kw_only=True)
class Detour(LowerIsBetter):
    """How many times longer the route is than a straight line between its ends."""

    format: str = "%.2f"

    def measure(self, ride: Ride):
        (lat1, lon1), (lat2, lon2) = ride.points[0], ride.points[-1]
        _, _, straight_m = _GEOD.inv(lon1, lat1, lon2, lat2)
        km = total_km(ride.edges)
        return km / (straight_m / 1000) if straight_m and km else None
