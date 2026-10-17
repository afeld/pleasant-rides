import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from ..models import Point
from .base import Provider

SOURCE = Path(__file__).with_suffix(".swift")
BINARY = Path(__file__).parent / ".build" / "apple"


async def _run(*args: str, timeout: float):
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


class Apple(Provider):
    """Requires macOS with the Xcode command line tools. Uses on-device MapKit, so no API key."""

    name = "Apple Maps"

    async def fetch(self, origin: Point, destination: Point):
        stdout = await _run(
            str(await _binary()),
            str(origin.lat),
            str(origin.lon),
            str(destination.lat),
            str(destination.lon),
            timeout=60,
        )
        routes = json.loads(stdout)
        return [(_label(r), r["points"]) for r in routes]


def _label(route: dict[str, Any]):
    """e.g. 'via NY-9D (Bike paths and main roads; May require walking)'"""
    label = f"via {route['name']}" if route["name"] else "Route"
    advisories = [a.rstrip(".") for a in route["advisories"]]
    if advisories:
        label += f" ({'; '.join(advisories)})"
    return label
