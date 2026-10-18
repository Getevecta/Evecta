"""Per-device trust for admin login 2FA (15-day remembered devices)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

ADMIN_DEVICE_TRUST_COOKIE = "admin_device_trust"
ADMIN_DEVICE_TRUST_DAYS = 15
ADMIN_DEVICE_TRUST_SECONDS = ADMIN_DEVICE_TRUST_DAYS * 24 * 3600


def _trust_redis_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"admin_device_trust:{digest}"


async def create_admin_device_trust(user_id: str) -> str:
    """
    Issue a new opaque device-trust token for this admin user.
    Stored hashed in Redis with a 15-day TTL.
    """
    from app.core.redis import get_redis

    token = secrets.token_urlsafe(32)
    redis = get_redis()
    await redis.set(_trust_redis_key(token), str(user_id), ex=ADMIN_DEVICE_TRUST_SECONDS)
    return token


async def validate_admin_device_trust(token: Optional[str], user_id: str) -> bool:
    """True if ``token`` is a live trust cookie for this user (within 15 days)."""
    if not token:
        return False
    from app.core.redis import get_redis

    redis = get_redis()
    stored = await redis.get(_trust_redis_key(token))
    if stored is None:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode()
    return str(stored) == str(user_id)


async def revoke_admin_device_trust(token: Optional[str]) -> None:
    """Drop trust for this device (logout / expired)."""
    if not token:
        return
    from app.core.redis import get_redis

    redis = get_redis()
    await redis.delete(_trust_redis_key(token))


async def revoke_all_admin_device_trust_for_user(user_id: str) -> int:
    """Revoke every remembered-device token issued for this user."""
    from app.core.redis import get_redis

    redis = get_redis()
    target = str(user_id)
    revoked = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor=cursor, match="admin_device_trust:*", count=100)
        for key in keys:
            stored = await redis.get(key)
            if stored is not None and str(stored) == target:
                await redis.delete(key)
                revoked += 1
        if cursor == 0:
            break
    return revoked
