"""Outbound HTTP for user-controlled URLs: pin DNS, no auto-redirects."""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx

from app.utils.outbound_host import try_resolve_public_ip

HTTP_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 5
MAX_BODY_BYTES = 2 * 1024 * 1024
_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_safe_http_url(url: str) -> tuple[str, str, int] | None:
    """Return (normalized_url, hostname, port) or None if the URL is not fetchable."""
    raw = (url or "").strip()
    if not raw or any(c in raw for c in ("\r", "\n", "\x00")):
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    hostname = parsed.hostname
    if not hostname:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in HTTP_PORTS:
        return None
    return raw, hostname, port


def _pinned_url(url: str, hostname: str, pinned_ip: str) -> httpx.URL:
    original = httpx.URL(url)
    host = pinned_ip
    if ":" in pinned_ip and not pinned_ip.startswith("["):
        host = pinned_ip
    return original.copy_with(host=host)


def _request_headers(hostname: str, extra: dict[str, str] | None) -> dict[str, str]:
    headers = dict(_DEFAULT_HEADERS)
    if extra:
        headers.update(extra)
    headers["Host"] = hostname
    return headers


def _next_location(current_url: str, response: httpx.Response) -> str | None:
    location = response.headers.get("location")
    if not location:
        return None
    return urljoin(current_url, location.strip())


def _prepare(url: str, extra_headers: dict[str, str] | None) -> tuple[httpx.Request, str] | None:
    parsed = parse_safe_http_url(url)
    if parsed is None:
        return None
    _, hostname, _port = parsed
    resolved = try_resolve_public_ip(hostname)
    if resolved is None:
        return None
    hostname, pinned_ip = resolved
    pinned = _pinned_url(url, hostname, pinned_ip)
    request = httpx.Request(
        "GET",
        pinned,
        headers=_request_headers(hostname, extra_headers),
        extensions={"sni_hostname": hostname},
    )
    return request, url


def _decode_body(response: httpx.Response) -> str:
    data = response.content[:MAX_BODY_BYTES]
    encoding = response.encoding or "utf-8"
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def safe_http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> str | None:
    current = url
    kwargs: dict = {"timeout": timeout, "follow_redirects": False, "trust_env": False}
    if transport is not None:
        kwargs["transport"] = transport
    for _ in range(MAX_REDIRECTS + 1):
        prepared = _prepare(current, headers)
        if prepared is None:
            return None
        request, requested_url = prepared
        try:
            with httpx.Client(**kwargs) as client:
                response = client.send(request)
                response.read()
        except httpx.HTTPError:
            return None

        if response.status_code in _REDIRECT_STATUS:
            nxt = _next_location(requested_url, response)
            if not nxt or parse_safe_http_url(nxt) is None:
                return None
            current = nxt
            continue
        if response.status_code != 200:
            return None
        return _decode_body(response)
    return None


async def async_safe_http_get_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    current = url
    kwargs: dict = {"timeout": timeout, "follow_redirects": False, "trust_env": False}
    if transport is not None:
        kwargs["transport"] = transport
    for _ in range(MAX_REDIRECTS + 1):
        prepared = _prepare(current, headers)
        if prepared is None:
            return None
        request, requested_url = prepared
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.send(request)
                await response.aread()
        except httpx.HTTPError:
            return None

        if response.status_code in _REDIRECT_STATUS:
            nxt = _next_location(requested_url, response)
            if not nxt or parse_safe_http_url(nxt) is None:
                return None
            current = nxt
            continue
        if response.status_code != 200:
            return None
        return _decode_body(response)
    return None
