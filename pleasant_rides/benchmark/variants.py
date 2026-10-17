"""The provider variants the Benchmark page compares, on the sample trips in `trips`. Add a variant to VARIANTS to try it."""

from ..providers import PROVIDERS
from ..providers.base import Provider
from ..providers.brouter import BRouter
from ..providers.graphhopper import GraphHopper
from ..providers.valhalla import PLEASANT_OPTIONS, Valhalla

# the stronger penalties tried on BRouter's pleasant.brf
STRONGER_BROUTER = {
    "fast_penalty": 2,
    "lanes_penalty": 1,
    "uphillcost": 100,
    "primary_cost": 3,
    "secondary_cost": 2,
    "tertiary_cost": 1.3,
    "consider_traffic": 1.5,
}

# by name; the providers as the app uses them come first, as the baselines
VARIANTS: dict[str, Provider] = {
    **{f"{name} (current)": provider for name, provider in PROVIDERS.items()},
    "Valhalla: previous (road bike, use_roads 0.2)": Valhalla(
        {
            "bicycle_type": "road",
            "use_roads": 0.2,
            "use_hills": 0.3,
            "use_ferry": 0.0,
            "avoid_bad_surfaces": 0.8,
        }
    ),
    "Valhalla: + turn penalty, living streets": Valhalla(
        {**PLEASANT_OPTIONS, "maneuver_penalty": 30, "use_living_streets": 1.0}
    ),
    "Valhalla: avoid ferries": Valhalla({**PLEASANT_OPTIONS, "use_ferry": 0.0}),
    "Valhalla: use_hills 0.1": Valhalla({**PLEASANT_OPTIONS, "use_hills": 0.1}),
    "BRouter: pleasant, stronger penalties": BRouter(params=STRONGER_BROUTER),
    "BRouter: pleasant + forests/rivers": BRouter(
        params={"consider_forest": True, "consider_river": True}
    ),
    **{
        f"BRouter: {profile}": BRouter(profile)
        for profile in [
            "fastbike-lowtraffic",
            "fastbike-verylowtraffic",
            "racebike-verylowtraffic",
            "safety",
            "trekking",
        ]
    },
    "BRouter: quaelnix-gravel, traffic/cycle routes/inclines": BRouter(
        "quaelnix-gravel",
        {
            "consider_traffic_estimate": True,
            "prefer_cycle_routes": True,
            "avoid_steep_inclines": True,
        },
    ),
    # other cycling profiles and custom models need a paid plan
    "GraphHopper: custom model": GraphHopper(custom_model=True),
}
