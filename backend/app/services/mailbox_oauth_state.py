"""Server-side Gmail mailbox OAuth state (Redis, one-time consume)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

MAILBOX_OAUTH_TTL = 600
_KEY_PREFIX = "mailbox_oauth_state:"


async def store_mailbox_oauth_state(
    *,
    state: str,
    user_id: str,
    campaign_id: Optional[str],
) -> None:
    from app.core.redis import get_redis

    payload = {
        "user_id": str(user_id),
        "campaign_id": campaign_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    redis = get_redis()
    await redis.set(f"{_KEY_PREFIX}{state}", json.dumps(payload), ex=MAILBOX_OAUTH_TTL)


async def consume_mailbox_oauth_state(state: str) -> Optional[dict]:
    from app.core.redis import get_redis

    if not state:
        return None
    redis = get_redis()
    raw = await redis.getdel(f"{_KEY_PREFIX}{state}")
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not data.get("user_id"):
        return None
    return data
