from dataclasses import dataclass
from typing import NamedTuple


class Point(NamedTuple):
    lat: float
    lon: float


@dataclass(frozen=True)
class Route:
    provider: str
    # what the provider says about the route, e.g. "Best route via Empire State Trl"; unique per provider
    label: str
    points: tuple[Point, ...]

    @property
    def id(self):
        return (self.provider, self.label)
