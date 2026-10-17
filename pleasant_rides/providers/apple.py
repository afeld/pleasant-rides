import asyncio
import json
import subprocess
from pathlib import Path

from ._labels import unique

SOURCE = Path(__file__).with_suffix(".swift")
BINARY = Path(__file__).parent / ".build" / "apple"


async def _run(*args, timeout):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        raise
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, stdout, stderr.decode())
    return stdout


async def _binary():
    # compiling takes ~20s, so only do it when the source changes
    if not BINARY.exists() or BINARY.stat().st_mtime < SOURCE.stat().st_mtime:
        BINARY.parent.mkdir(exist_ok=True)
        await _run("swiftc", "-O", str(SOURCE), "-o", str(BINARY), timeout=300)
    return BINARY


async def get_routes(origin, destination):
    """Requires macOS with the Xcode command line tools. Uses on-device MapKit, so no API key."""
    stdout = await _run(
        str(await _binary()),
        str(origin["lat"]),
        str(origin["lon"]),
        str(destination["lat"]),
        str(destination["lon"]),
        timeout=60,
    )
    routes = json.loads(stdout)
    labels = unique(_label(r) for r in routes)
    return [(label, [tuple(p) for p in r["points"]]) for label, r in zip(labels, routes)]


def _label(route):
    """e.g. 'via NY-9D (Bike paths and main roads; May require walking)'"""
    label = f"via {route['name']}" if route["name"] else "Route"
    advisories = [a.rstrip(".") for a in route["advisories"]]
    if advisories:
        label += f" ({'; '.join(advisories)})"
    return label
