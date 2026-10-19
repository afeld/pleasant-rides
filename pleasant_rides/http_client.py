"""HTTP requests that identify the app, so the people running the (often free) servers it uses know who's calling and
where to find out more, as e.g. Nominatim's usage policy asks."""

import httpx

USER_AGENT = "pleasant-rides (+https://github.com/afeld/pleasant-rides)"
HEADERS = {"User-Agent": USER_AGENT}


def client(**kwargs):
    """An httpx.AsyncClient that sends the app's User-Agent."""
    return httpx.AsyncClient(headers=HEADERS, **kwargs)


def get(url: str, **kwargs):
    """httpx.get(), sending the app's User-Agent."""
    return httpx.get(url, headers=HEADERS, **kwargs)


def post(url: str, **kwargs):
    """httpx.post(), sending the app's User-Agent."""
    return httpx.post(url, headers=HEADERS, **kwargs)
