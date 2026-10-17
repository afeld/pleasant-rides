import json
import subprocess
from pathlib import Path

SOURCE = Path(__file__).with_suffix(".swift")
BINARY = Path(__file__).parent / ".build" / "apple"


def _binary():
    # compiling takes ~20s, so only do it when the source changes
    if not BINARY.exists() or BINARY.stat().st_mtime < SOURCE.stat().st_mtime:
        BINARY.parent.mkdir(exist_ok=True)
        subprocess.run(["swiftc", "-O", str(SOURCE), "-o", str(BINARY)], check=True)
    return BINARY


def get_routes(origin, destination):
    """Requires macOS with the Xcode command line tools. Uses on-device MapKit, so no API key."""
    result = subprocess.run(
        [
            str(_binary()),
            str(origin["lat"]),
            str(origin["lon"]),
            str(destination["lat"]),
            str(destination["lon"]),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    routes = json.loads(result.stdout)
    return [
        (f"Apple {i}", [tuple(p) for p in points])
        for i, points in enumerate(routes, start=1)
    ]
