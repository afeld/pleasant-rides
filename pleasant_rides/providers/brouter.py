import httpx

URL = "https://brouter.de/brouter"


async def get_routes(origin, destination, profile="trekking"):
    # https://github.com/abrensch/brouter/blob/master/brouter-server/src/main/resources/readme.md
    async with httpx.AsyncClient() as client:
        response = await client.get(
            URL,
            params={
                "lonlats": f"{origin.lon},{origin.lat}|{destination.lon},{destination.lat}",
                "profile": profile,
                "alternativeidx": 0,
                "format": "geojson",
            },
            timeout=120.0,
        )
    response.raise_for_status()
    feature = response.json()["features"][0]
    # GeoJSON coordinates are [lon, lat(, elevation)]
    points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
    return [(f"BRouter ({profile})", points)]
