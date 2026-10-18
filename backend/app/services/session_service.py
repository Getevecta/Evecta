"""Auth session orchestration: issue tokens, write/clear cookies, client IP.

JWT minting stays in ``utils/jwt.py`` and refresh-token persistence stays in
``token_service.py``. Callers that establish or end a browser session should
go through this module rather than assembling those primitives themselves.
"""
from __future__ import annotations

import uuid

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import environment_cookie_secure, get_settings
from app.services.admin_device_trust import (
    ADMIN_DEVICE_TRUST_COOKIE,
    ADMIN_DEVICE_TRUST_SECONDS,
)
from app.services.token_service import store_refresh_token
from app.utils.jwt import create_access_token, create_refresh_token

settings = get_settings()


def environment_name() -> str:
    return get_settings().environment_name


def is_production() -> bool:
    """Canonical production-like check (live prod and staging)."""
    return get_settings().is_production


def is_local_dev() -> bool:
    """Canonical local/dev policy for logging and fail-open tooling."""
    return get_settings().is_local_dev


def cookie_secure(request_is_https: bool = False) -> bool:
    """Secure unless APP_ENVIRONMENT is an explicit local/dev name."""
    return environment_cookie_secure(get_settings().environment_name, request_is_https)


def client_ip_from_request(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    secure: bool,
    refresh_max_age: int | None = None,
    device_trust_token: str | None = None,
    access_samesite: str = "strict",
    refresh_samesite: str = "lax",
) -> None:
    """Set HttpOnly access + refresh cookies. OAuth redirects should use SameSite=lax."""
    refresh_age = refresh_max_age
    if refresh_age is None:
        refresh_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600

    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure,
        samesite=access_samesite,
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure,
        samesite=refresh_samesite,
        path="/",
        max_age=refresh_age,
    )
    if device_trust_token:
        response.set_cookie(
            key=ADMIN_DEVICE_TRUST_COOKIE,
            value=device_trust_token,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
            max_age=ADMIN_DEVICE_TRUST_SECONDS,
        )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    """Expire access/refresh cookies. Leaves admin device-trust in place."""
    # Access is SameSite=strict on password login and lax on OAuth redirects.
    for key, samesite in (
        ("access_token", "strict"),
        ("access_token", "lax"),
        ("refresh_token", "lax"),
    ):
        response.delete_cookie(
            key=key,
            path="/",
            httponly=True,
            secure=secure,
            samesite=samesite,
        )


def _as_user_id(user_id: uuid.UUID | str) -> uuid.UUID:
    return user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))


async def issue_session(
    session: AsyncSession,
    user_id: uuid.UUID | str,
    *,
    refresh_expire_days: int | None = None,
) -> dict:
    """Mint access + refresh JWTs and persist the refresh token."""
    uid = _as_user_id(user_id)
    access_token = create_access_token(uid)
    refresh_token, jti, expires_at = create_refresh_token(
        uid,
        expire_days=refresh_expire_days,
    )
    await store_refresh_token(session, uid, jti, expires_at)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "refresh_expires_at": expires_at,
    }


async def establish_session(
    db: AsyncSession,
    response: Response,
    user_id: uuid.UUID | str,
    *,
    secure: bool,
    refresh_expire_days: int | None = None,
    refresh_max_age: int | None = None,
    device_trust_token: str | None = None,
    access_samesite: str = "strict",
    refresh_samesite: str = "lax",
) -> dict:
    """Issue a session and attach auth cookies to ``response``."""
    tokens = await issue_session(
        db,
        user_id,
        refresh_expire_days=refresh_expire_days,
    )
    set_auth_cookies(
        response,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        secure=secure,
        refresh_max_age=refresh_max_age,
        device_trust_token=device_trust_token,
        access_samesite=access_samesite,
        refresh_samesite=refresh_samesite,
    )
    return tokens
