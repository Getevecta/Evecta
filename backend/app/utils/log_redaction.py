"""Strip secrets from values before they are written to logs."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url_credentials(url: str | None) -> str:
    """Return *url* with userinfo removed (``redis://:pass@host`` → ``redis://host``)."""
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
