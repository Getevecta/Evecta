"""Enrichment concurrency caps: per-process semaphore + cluster-wide Redis slots.

``asyncio.Semaphore`` only coordinates inside one worker. Celery runs several
worker processes, so Hunter/HTTP/Maps/Gemini would otherwise be capped at
N×limit. Redis ZSET slots are the shared counter; the local semaphore remains
the in-process bound and the fallback when Redis is down.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import time
import uuid

logger = logging.getLogger(__name__)

LIMITS = {
    "hunter": 20,
    "http": 20,
    "google_maps": 25,
    "email": 20,
    "context": 20,
}

LEASE_MS = 120_000
KEY_PREFIX = "enrich:sem:"
_POLL_MIN = 0.05
_POLL_MAX = 0.25

_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local token = ARGV[3]
local lease = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, now + lease, token)
  redis.call('PEXPIRE', key, lease)
  return 1
end
return 0
"""

_RELEASE_LUA = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""

_acquire_script = None
_release_script = None


def _load_scripts():
    global _acquire_script, _release_script
    from app.utils.redis_context import REDIS_AVAILABLE, redis_client

    if not REDIS_AVAILABLE or redis_client is None:
        return None, None
    if _acquire_script is None:
        try:
            _acquire_script = redis_client.register_script(_ACQUIRE_LUA)
            _release_script = redis_client.register_script(_RELEASE_LUA)
        except Exception:
            logger.warning("[ENRICH SEM] Could not register Redis limiter scripts", exc_info=True)
            return None, None
    return _acquire_script, _release_script


def try_acquire_slot_sync(name: str, limit: int, token: str, now_ms: int | None = None) -> bool:
    """Atomically take one cluster slot. True = proceed (held or Redis unavailable)."""
    acquire, _ = _load_scripts()
    if acquire is None:
        return True
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    try:
        held = acquire(
            keys=[f"{KEY_PREFIX}{name}"],
            args=[now, int(limit), token, LEASE_MS],
        )
        return int(held or 0) == 1
    except Exception:
        logger.warning("[ENRICH SEM] Redis acquire failed for %s; using process cap only", name)
        return True


def release_slot_sync(name: str, token: str) -> None:
    _, release = _load_scripts()
    if release is None:
        return
    try:
        release(keys=[f"{KEY_PREFIX}{name}"], args=[token])
    except Exception:
        logger.warning("[ENRICH SEM] Redis release failed for %s", name)


class RedisBoundedSemaphore:
    """Local asyncio.Semaphore plus a Redis slot of the same limit."""

    def __init__(self, name: str, limit: int):
        self.name = name
        self.limit = limit
        self._local = asyncio.Semaphore(limit)
        self._token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"enrich_sem_{name}", default=None
        )

    async def __aenter__(self) -> "RedisBoundedSemaphore":
        await self._local.acquire()
        token = uuid.uuid4().hex
        try:
            from app.utils.redis_context import arun

            delay = _POLL_MIN
            while True:
                if await arun(try_acquire_slot_sync, self.name, self.limit, token):
                    self._token.set(token)
                    return self
                await asyncio.sleep(delay)
                delay = min(delay * 1.5, _POLL_MAX)
        except BaseException:
            self._local.release()
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        token = self._token.get()
        try:
            if token:
                from app.utils.redis_context import arun

                await arun(release_slot_sync, self.name, token)
        finally:
            self._token.set(None)
            self._local.release()


class EnrichmentSemaphores:
    def __init__(self):
        self.hunter = RedisBoundedSemaphore("hunter", LIMITS["hunter"])
        self.http = RedisBoundedSemaphore("http", LIMITS["http"])
        self.google_maps = RedisBoundedSemaphore("google_maps", LIMITS["google_maps"])
        self.email = RedisBoundedSemaphore("email", LIMITS["email"])
        # Per-lead website-context scrape + LLM extraction. Fully async (async httpx +
        # Gemini ainvoke), so it scales on I/O rather than threads. Capped to stay within
        # Gemini rate limits rather than the old thread-pool ceiling.
        self.context = RedisBoundedSemaphore("context", LIMITS["context"])


_semaphores: EnrichmentSemaphores | None = None


def get_enrichment_semaphores() -> EnrichmentSemaphores:
    """Shared caps: local semaphore per process, Redis ZSET across workers."""
    global _semaphores
    if _semaphores is None:
        _semaphores = EnrichmentSemaphores()
    return _semaphores
