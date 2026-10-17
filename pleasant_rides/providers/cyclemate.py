import os

import httpx

URL = "https://api.cyclemate.club/directions/v2/"


def get_routes(origin, destination):
    """Requires CYCLEMATE_API_KEY (request one via https://docs.cyclemate.club)."""
    api_key = os.environ["CYCLEMATE_API_KEY"]
    response = httpx.post(
        URL,
        headers={"apikey": api_key},
        json={
            "coordinates": [
                [origin["lon"], origin["lat"]],
                [destination["lon"], destination["lat"]],
            ],
            "profile": "cycling",
            "supersafe": True,
        },
        timeout=60.0,
    )
    response.raise_for_status()
    route = response.json()["route"]
    if route is None:
        return []
    # GeoJSON coordinates are [lon, lat]
    points = [(c[1], c[0]) for c in route["geometry"]["coordinates"]]
    return [("SuperSafe", points)]
