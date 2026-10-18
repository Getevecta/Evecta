"""Helpers for safe, user-facing HTTP errors (never interpolate raw exceptions)."""

from __future__ import annotations

import logging
from typing import Any, NoReturn

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

SAFE_GENERIC = "Something went wrong. Please try again."
SAFE_DB = "A database error occurred. Please try again."
SAFE_AUTH = "Authentication failed. Please try again."
SAFE_PAYMENT = "Payment request failed. Please try again."
SAFE_EMAIL = "Failed to send email. Please try again."
SAFE_CHAT = "Chat processing failed. Please try again."
SAFE_SEARCH = "Lead search failed. Please try again."
SAFE_SESSION = "Your session could not be updated. Please sign in again."


def raise_safe(
    status_code: int,
    *,
    detail: str = SAFE_GENERIC,
    exc: BaseException | None = None,
    log_message: str | None = None,
) -> NoReturn:
    """Raise HTTPException with a safe detail; log the real exception if provided."""
    if exc is not None:
        logger.exception(log_message or detail)
    raise HTTPException(status_code=status_code, detail=detail)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Defense-in-depth: never return raw exception text for unhandled errors."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": SAFE_GENERIC})


def looks_like_raw_exception(detail: Any) -> bool:
    """Heuristic: HTTPException details that look like stack/provider dumps."""
    if not isinstance(detail, str):
        return False
    lower = detail.lower()
    markers = (
        "traceback (most recent call last)",
        "greenlet_spawn",
        "sqlalchemy.",
        "psycopg",
        "asyncpg",
        "operationalerror",
        "integrityerror",
        "resourceexhausted",
        'file "/',
        "await_only()",
    )
    if any(m in lower for m in markers):
        return True
    # Long technical dumps
    if len(detail) > 280 and ("\n" in detail or " at 0x" in lower):
        return True
    return False


async def http_exception_sanitizer(request: Request, exc: HTTPException) -> JSONResponse:
    """Sanitize accidental raw exception strings in HTTPException.detail."""
    detail = exc.detail
    if looks_like_raw_exception(detail):
        logger.error(
            "Sanitized unsafe HTTPException detail on %s %s: %s",
            request.method,
            request.url.path,
            detail if isinstance(detail, str) else repr(detail),
        )
        detail = SAFE_GENERIC
    headers = getattr(exc, "headers", None)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=headers)
