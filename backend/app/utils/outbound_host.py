"""Reject private/reserved destinations before SMTP/IMAP connections (SSRF)."""
from __future__ import annotations

import ipaddress
import socket
from typing import Literal

from fastapi import HTTPException, status

SMTP_PORTS = frozenset({25, 465, 587, 2525})
IMAP_PORTS = frozenset({143, 993})
_UNSAFE_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".corp")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _blocked_ip(ip.ipv4_mapped)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    if ip.version == 4 and ip in _CGNAT:
        return True
    return False


def assert_safe_outbound_port(port: int, kind: Literal["smtp", "imap"]) -> None:
    allowed = SMTP_PORTS if kind == "smtp" else IMAP_PORTS
    if port not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported {kind.upper()} port. Allowed: {sorted(allowed)}.",
        )


def resolve_public_ip(host: str) -> tuple[str, str]:
    """Return (hostname, pinned_ip). Rejects private/reserved/metadata addresses."""
    hostname = (host or "").strip().rstrip(".")
    if not hostname or any(c.isspace() or c == "\x00" for c in hostname):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid host.",
        )
    lowered = hostname.lower()
    if lowered == "localhost" or any(lowered.endswith(sfx) for sfx in _UNSAFE_SUFFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That host is not allowed.",
        )

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That host is not allowed.",
            )
        return hostname, str(literal)

    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not resolve host.",
        ) from None

    ips: list[str] = []
    for info in infos:
        addr = info[4][0]
        try:
            parsed = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _blocked_ip(parsed):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That host is not allowed.",
            )
        ips.append(str(parsed))

    if not ips:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not resolve host.",
        )
    return hostname, ips[0]


def try_resolve_public_ip(host: str) -> tuple[str, str] | None:
    """Like resolve_public_ip, but returns None instead of raising HTTPException."""
    try:
        return resolve_public_ip(host)
    except HTTPException:
        return None
