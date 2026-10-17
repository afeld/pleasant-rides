import os
from abc import ABC, abstractmethod
from collections.abc import Sequence

from ..models import Point, Route

# a label and [(lat, lon), ...], as a provider's API gives them
RawRoute = tuple[str, Sequence[tuple[float, float]]]


class MissingAPIKey(Exception):
    pass


class Provider(ABC):
    name: str
    # the environment variable holding this provider's API key, if it needs one
    api_key_var: str | None = None

    @property
    def api_key(self):
        key = os.environ.get(self.api_key_var) if self.api_key_var else None
        if not key:
            raise MissingAPIKey(f"set {self.api_key_var}")
        return key

    @property
    def cache_key(self):
        """Identifies the provider and its settings, so their routes can be cached."""
        return f"{type(self).__name__}({vars(self)!r})"

    @abstractmethod
    async def fetch(self, origin: Point, destination: Point) -> Sequence[RawRoute]:
        """Returns the routes from the provider's API."""

    async def get_routes(self, origin: Point, destination: Point):
        routes = await self.fetch(origin, destination)
        # the app identifies routes by provider and label, so number any repeats
        labels = _unique([label for label, _ in routes])
        return [
            Route(self.name, label, tuple(Point(*p) for p in points))
            for label, (_, points) in zip(labels, routes)
        ]


def _unique(labels: list[str]):
    counts: dict[str, int] = {}
    result: list[str] = []
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
        result.append(label if counts[label] == 1 else f"{label} ({counts[label]})")
    return result
