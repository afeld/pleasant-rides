"""Tests for the route page, with its data faked so that they don't hit the network."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from streamlit.testing.v1 import AppTest

from pleasant_rides.models import Point, Route
from pleasant_rides.scoring import METRICS, Scorecard
from pleasant_rides.trips import TRIPS

TRIP = next(iter(TRIPS))
ROUTE = Route("Valhalla", "Primary", (Point(40.75, -73.98), Point(40.76, -73.98)))
EDGES = [
    {
        "length": 1.0,
        "use": "road",
        "road_class": "residential",
        "lane_count": 2,
        "surface": "paved_smooth",
        "mean_elevation": 10,
    },
    {"length": 2.0, "use": "cycleway", "mean_elevation": 20},
]
VALUES = {m.key: None for m in METRICS} | {"distance_mi": 1.9, "low_traffic": 0.75}


@pytest.fixture
def fetch_routes() -> Iterator[AsyncMock]:
    with (
        patch(
            "pleasant_rides.cached.fetch_routes", new=AsyncMock(return_value=[ROUTE])
        ) as fetch,
        patch("pleasant_rides.cached.get_edges", new=AsyncMock(return_value=EDGES)),
        patch(
            "pleasant_rides.scored_routes.get_edges", new=AsyncMock(return_value=EDGES)
        ),
        patch(
            "pleasant_rides.scored_routes.get_surroundings",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "pleasant_rides.scored_routes.score_ride",
            new=MagicMock(return_value=Scorecard(VALUES, 72)),
        ),
    ):
        yield fetch


def open_route(**params: str):
    app = AppTest.from_file("../app.py", default_timeout=30).run()
    app.query_params.update(params)
    return app.switch_page("app_pages/route.py").run()


def all_text(app: AppTest):
    return " ".join(block.value for block in [*app.markdown, *app.caption, *app.title])


def test_shows_the_route(fetch_routes: AsyncMock):
    app = open_route(trip_name=TRIP, provider="Valhalla", route="Primary")

    assert not app.exception
    assert not app.error
    assert app.title[0].value == "Valhalla: Primary"
    assert TRIP in all_text(app)
    assert fetch_routes.await_count == 1
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Score"] == "72"
    assert metrics["Low traffic"] == "75%"
    assert [h.value for h in app.subheader] == [
        "Elevation",
        "What it rides on",
        "Along the route",
        "How it scored",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"trip_name": "Nowhere", "provider": "Valhalla", "route": "Primary"},
        {"trip_name": TRIP, "provider": "Nobody", "route": "Primary"},
        {"trip_name": TRIP, "provider": "Valhalla", "route": "No such route"},
    ],
)
def test_says_when_it_cant_find_the_route(
    fetch_routes: AsyncMock, params: dict[str, str]
):
    app = open_route(**params)

    assert not app.exception
    assert "Couldn't find that route" in app.error[0].value
    assert not app.metric


def test_says_when_the_provider_fails(fetch_routes: AsyncMock):
    fetch_routes.side_effect = RuntimeError("down")
    app = open_route(trip_name=TRIP, provider="Valhalla", route="Primary")

    assert not app.exception
    assert "down" in app.error[0].value


def test_custom_trips_are_found_from_their_places(fetch_routes: AsyncMock):
    with patch("pleasant_rides.cached.geocode", return_value=ROUTE.points[0]):
        app = open_route(
            trip_name="Custom…",
            provider="Valhalla",
            route="Primary",
            **{"from": "Here", "to": "There"},
        )

    assert not app.exception
    assert "Here → There" in all_text(app)
    assert app.metric


def test_custom_trips_need_signing_in(
    fetch_routes: AsyncMock, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("REQUIRE_LOGIN", "1")
    app = open_route(
        trip_name="Custom…",
        **{"from": "Here", "to": "There"},
        provider="Valhalla",
        route="Primary",
    )

    assert not app.exception
    assert fetch_routes.await_count == 0
    assert not app.metric
