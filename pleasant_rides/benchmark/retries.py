"""Retrying failed requests, politely: only errors that might go away, and never to a server that's asked for fewer."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ..politeness import is_rate_limited, is_retryable
from ..providers.base import MissingAPIKey

# for errors that might go away, like a busy server; see politeness.is_retryable()
ATTEMPTS = 3
RETRY_AFTER_S = 10

T = TypeVar("T")


class Backoffs:
    """Which servers have asked for fewer requests during a run, so they don't get any more."""

    def __init__(self):
        # server -> why it's skipped
        self.reasons: dict[str, str] = {}

    async def attempt(self, server: str, call: Callable[[], Awaitable[T]]) -> T | str:
        """Returns what `call()` does, or an error message.

        Only retries errors that might go away (like a busy server), and not at all once `server` has rate-limited us.
        """
        if server in self.reasons:
            return self.reasons[server]
        error = ""
        for attempt in range(ATTEMPTS):
            if attempt:
                await asyncio.sleep(RETRY_AFTER_S)
            try:
                return await call()
            except MissingAPIKey as e:
                return f"skipped ({e})"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"
                if is_rate_limited(e):
                    self.reasons[server] = (
                        f"skipped, since {server} asked for fewer requests ({error})"
                    )
                    return error
                if not is_retryable(e):
                    return error
        return error
