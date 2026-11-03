import pytest

from pleasant_rides.edges import describe


@pytest.mark.parametrize(
    "edge, description",
    [
        ({"use": "cycleway", "surface": "paved_smooth"}, "cycleway, smooth pavement"),
        (
            {
                "use": "road",
                "road_class": "secondary",
                "lane_count": 4,
                "cycle_lane": "separated",
                "surface": "paved",
            },
            "secondary road, 4 lanes, protected bike lane, paved",
        ),
        (
            {
                "use": "road",
                "road_class": "residential",
                "lane_count": 1,
                "cycle_lane": "none",
            },
            "residential road, 1 lane",
        ),
        ({"use": "living_street"}, "living street"),
        ({}, "road"),
    ],
)
def test_describe(edge: dict, description: str):
    assert describe(edge) == description
