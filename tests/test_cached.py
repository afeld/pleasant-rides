import asyncio
from pathlib import Path

import pytest
import streamlit as st
from streamlit.runtime.caching import cache_data_api
from streamlit.runtime.caching.storage.local_disk_cache_storage import (
    LocalDiskCacheStorageManager,
)

from pleasant_rides import cached
from pleasant_rides.metrics import Ride
from pleasant_rides.models import Point
from pleasant_rides.scoring import Scorecard

calls: list[int] = []


@st.cache_data(persist="disk")
def double(x: int):
    calls.append(x)
    return x * 2


@st.cache_data(persist="disk")
async def triple(x: int):
    calls.append(x)
    return x * 3


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """An empty disk cache, rather than ~/.streamlit/cache. Outside a running app, Streamlit only caches in memory, so this uses the app's storage instead."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        cache_data_api._data_caches,
        "get_storage_manager",
        LocalDiskCacheStorageManager,
    )
    calls.clear()
    return tmp_path / ".streamlit" / "cache"


def empty_entries(cache_dir: Path):
    """Leaves the disk cache's files empty, as an unfinished write does, and forgets what's in memory, as a restart does."""
    for path in cache_dir.glob("*.memo"):
        path.write_bytes(b"")
    cache_data_api._data_caches._function_caches.clear()


def test_recomputes_an_empty_entry(cache_dir: Path):
    assert cached.call(double, 2) == 4
    empty_entries(cache_dir)

    assert cached.call(double, 2) == 4
    assert calls == [2, 2]
    # and stores it again
    assert cached.call(double, 2) == 4
    assert calls == [2, 2]


def test_recomputes_an_empty_entry_async(cache_dir: Path):
    assert asyncio.run(cached.call_async(triple, 2)) == 6
    empty_entries(cache_dir)

    assert asyncio.run(cached.call_async(triple, 2)) == 6
    assert calls == [2, 2]


def test_score_ride_is_cached_until_the_scoring_code_changes(
    monkeypatch: pytest.MonkeyPatch,
):
    scored = []

    def score(ride: Ride):
        scored.append(ride)
        return Scorecard({}, 50.0)

    monkeypatch.setattr(cached.scoring, "score", score)
    monkeypatch.setattr(cached, "_latest_release", lambda: "2026-01-01.0")
    cached._score.clear()
    ride = Ride((Point(40.0, -74.0), Point(40.01, -74.0)), [], None)

    assert cached.score_ride(ride).total == 50
    cached.score_ride(ride)
    assert len(scored) == 1
    monkeypatch.setattr(cached, "_SCORING_CODE", "changed")
    cached.score_ride(ride)
    assert len(scored) == 2
