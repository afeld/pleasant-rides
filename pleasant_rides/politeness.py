"""Being polite to the providers' servers, particularly the free public ones: spacing out requests, and telling apart
errors worth retrying from ones that aren't."""

import asyncio
import time

import httpx

# server -> when the next request to it may be made, from time.monotonic()
_next_slot: dict[str, float] = {}


async def wait_turn(server: str, interval_s: float):
    """Waits until `interval_s` after the previous request to `server`, then claims that slot for the caller."""
    if not interval_s:
        return
    now = time.monotonic()
    slot = max(now, _next_slot.get(server, now))
    _next_slot[server] = slot + interval_s
    await asyncio.sleep(slot - now)


class ProviderError(RuntimeError):
    """An error response from a provider's API.

    `retryable` if trying again later might work, e.g. because the server was busy; `rate_limited` if the server asked
    for fewer requests, in which case it shouldn't get more for a while.
    """

    def __init__(
        self, message: str, *, retryable: bool = False, rate_limited: bool = False
    ):
        super().__init__(message)
        self.retryable = retryable
        self.rate_limited = rate_limited


def status_error(service: str, response: httpx.Response, detail: str):
    """A ProviderError for an error response, going by the usual meanings of HTTP status codes."""
    status = response.status_code
    return ProviderError(
        f"{service} {status}: {detail}",
        retryable=status >= 500,
        rate_limited=status == 429,
    )


def is_rate_limited(error: Exception):
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429
    return isinstance(error, ProviderError) and error.rate_limited


def is_retryable(error: Exception):
    """Whether trying again later might work, as opposed to errors like a bad request or a missing feature."""
    if is_rate_limited(error):
        # it might work later, but not soon enough to retry right away
        return False
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    # timeouts, dropped connections, and the like
    if isinstance(error, httpx.TransportError):
        return True
    return isinstance(error, ProviderError) and error.retryable
