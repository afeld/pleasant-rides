import asyncio
import time

import httpx
import pytest

from pleasant_rides.politeness import (
    ProviderError,
    is_rate_limited,
    is_retryable,
    status_error,
    wait_turn,
)


def response(status: int):
    return httpx.Response(status, request=httpx.Request("GET", "https://example.com"))


def test_wait_turn_spaces_out_requests_to_a_server():
    async def three_requests():
        started = time.monotonic()
        times = []
        for _ in range(3):
            await wait_turn("spaced.example.com", 0.05)
            times.append(time.monotonic() - started)
        return times

    first, second, third = asyncio.run(three_requests())
    assert first < 0.05
    assert second - first >= 0.04
    assert third - second >= 0.04


def test_wait_turn_spaces_out_concurrent_requests():
    async def concurrent():
        started = time.monotonic()

        async def request():
            await wait_turn("concurrent.example.com", 0.05)
            return time.monotonic() - started

        return sorted(await asyncio.gather(request(), request(), request()))

    first, second, third = asyncio.run(concurrent())
    assert second - first >= 0.04
    assert third - second >= 0.04


def test_wait_turn_without_an_interval_doesnt_wait():
    async def request():
        started = time.monotonic()
        await wait_turn("unthrottled.example.com", 0)
        await wait_turn("unthrottled.example.com", 0)
        return time.monotonic() - started

    assert asyncio.run(request()) < 0.01


@pytest.mark.parametrize(
    "status, retryable, rate_limited",
    [(400, False, False), (404, False, False), (429, False, True), (503, True, False)],
)
def test_status_errors(status, retryable, rate_limited):
    error = status_error("Test", response(status), "detail")
    assert str(error) == f"Test {status}: detail"
    assert is_retryable(error) == retryable
    assert is_rate_limited(error) == rate_limited


def test_httpx_errors():
    def status(code: int):
        return httpx.HTTPStatusError(
            "", request=response(code).request, response=response(code)
        )

    assert is_retryable(status(502))
    assert not is_retryable(status(400))
    assert is_rate_limited(status(429))
    assert not is_retryable(status(429))
    assert is_retryable(httpx.ReadTimeout("timed out"))


def test_other_errors_arent_retried():
    assert not is_retryable(RuntimeError("bug"))
    assert not is_retryable(
        ProviderError("rate limited", retryable=True, rate_limited=True)
    )
