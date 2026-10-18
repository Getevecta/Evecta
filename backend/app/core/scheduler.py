import asyncio
import logging
import secrets
from datetime import datetime, timezone
from app.database.session import async_session_factory

logger = logging.getLogger(__name__)
from app.services.reply_fetch_service import fetch_replies_for_all_mailboxes

_LOCK_KEY = "reply_fetcher:lock"
_LOCK_TTL = 600   # seconds — must exceed max expected fetch duration
_SLEEP_INTERVAL = 500  # seconds between cycles


async def reply_fetcher_loop():
    """
    Runs forever every ~8 minutes.

    Uses a Redis distributed lock so only ONE worker across all gunicorn/uvicorn
    processes runs the fetch per cycle. Other workers skip cleanly and retry
    next cycle — no duplicate mailbox polling or DB conflicts.
    """
    from app.core.redis import get_redis

    logger.info("[Scheduler] Reply fetcher started")

    while True:
        try:
            redis = get_redis()
            # Store a unique owner token so we only delete our own lock
            owner = secrets.token_hex(16)
            acquired = await redis.set(_LOCK_KEY, owner, nx=True, ex=_LOCK_TTL)

            if acquired:
                try:
                    logger.info("[Scheduler] Lock acquired — fetching replies at %s", datetime.now(timezone.utc))
                    async with async_session_factory() as db:
                        await fetch_replies_for_all_mailboxes(db)
                finally:
                    # Only delete if we still own the lock (atomic via Lua)
                    release_script = """
                        if redis.call("get", KEYS[1]) == ARGV[1] then
                            return redis.call("del", KEYS[1])
                        else
                            return 0
                        end
                    """
                    await redis.eval(release_script, 1, _LOCK_KEY, owner)
                    logger.info("[Scheduler] Lock released")
            else:
                logger.debug("[Scheduler] Lock held by another worker — skipping cycle")

        except Exception:
            logger.exception("[Scheduler] Unexpected error in reply fetcher loop")

        await asyncio.sleep(_SLEEP_INTERVAL)
