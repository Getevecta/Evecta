"""Process-level httpx client for Gmail and other outbound Google API calls.

Gmail reply-fetch and send must reuse this client for the whole mailbox cycle
(list, get, modify, send) instead of opening a new TLS session per API call.
"""
from __future__ import annotations

import httpx

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


def mailbox_cycle_client() -> httpx.AsyncClient:
    """Shared client for one Gmail mailbox fetch/send cycle. Do not close it."""
    return get_http_client()


async def init_http_client() -> None:
    get_http_client()


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None
