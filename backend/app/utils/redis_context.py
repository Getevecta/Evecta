import json
import uuid
import hashlib
import logging
import asyncio
import redis

logger = logging.getLogger(__name__)
from app.core.config import get_settings
from typing import Dict, Optional, List

settings = get_settings()

# Initialize Redis client
try:
    redis_client = redis.Redis.from_url(
        settings.redis_cache_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_keepalive=True,
        health_check_interval=30,
    )
    # Test connection
    redis_client.ping()
    REDIS_AVAILABLE = True
    logger.info("[REDIS] Successfully connected to Redis")
except Exception as e:
    logger.error(f"[REDIS] Failed to connect to Redis: {e}. Falling back to in-memory storage.")
    REDIS_AVAILABLE = False
    redis_client = None


# Fallback in-memory storage for the thread-id map (used when Redis is unavailable).
# Conversation context + history no longer live here — they're in the LangGraph
# ChatState (checkpointer); see chat_graph.py / chat_service.py.
_memory_thread: Dict[str, str] = {}

# Thread id = one conversation for the LangGraph checkpointer. Kept 30 days so a
# chat the user returns to stays on the same durable thread; "New Chat" rotates it.
_THREAD_TTL = 30 * 24 * 3600


def get_or_create_thread_id(user_key: str) -> str:
    """Return the user's current chat thread id, creating one if absent."""
    key = f"thread:{user_key}"
    if REDIS_AVAILABLE and redis_client:
        try:
            existing = redis_client.get(key)
            if existing:
                return existing
            new_id = uuid.uuid4().hex
            redis_client.setex(key, _THREAD_TTL, new_id)
            return new_id
        except Exception as e:
            logger.error(f"[REDIS] Error getting/creating thread id: {e}")
    if user_key not in _memory_thread:
        _memory_thread[user_key] = uuid.uuid4().hex
    return _memory_thread[user_key]


def peek_thread_id(user_key: str) -> Optional[str]:
    """Return the current Redis/fallback thread id without creating one."""
    key = f"thread:{user_key}"
    if REDIS_AVAILABLE and redis_client:
        try:
            existing = redis_client.get(key)
            if existing:
                return existing
        except Exception as e:
            logger.error(f"[REDIS] Error peeking thread id: {e}")
    return _memory_thread.get(user_key)


def rotate_thread_id(user_key: str) -> str:
    """Start a new conversation thread ('New Chat'). Returns the new thread id.

    Does not delete checkpointer state — the /chat/reset handler hard-deletes the
    abandoned thread's checkpoints before calling this.
    """
    new_id = uuid.uuid4().hex
    key = f"thread:{user_key}"
    if REDIS_AVAILABLE and redis_client:
        try:
            redis_client.setex(key, _THREAD_TTL, new_id)
            return new_id
        except Exception as e:
            logger.error(f"[REDIS] Error rotating thread id: {e}")
    _memory_thread[user_key] = new_id
    return new_id


async def arun(fn, /, *args, **kwargs):
    """Run a sync Redis helper off the event loop so async callers do not block."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# Conversation context + history are no longer stored in Redis — they live in the
# LangGraph ChatState (Postgres / in-memory checkpointer), the single source of truth.
# See chat_graph.py (nodes) and chat_service.py (phases). "New Chat" hard-deletes the
# previous thread's checkpoints, then rotates the Redis thread-id map.


# ── Google Places API cache helpers ──────────────────────────────────────────

def _places_cache_key(prefix: str, industry: str, location: str) -> str:
    """Stable, lowercase cache key derived from industry + location."""
    raw = f"{industry.strip().lower()}:{location.strip().lower()}"
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]
    return f"{prefix}:{digest}"


def get_cached_leads(industry: str, location: str) -> Optional[List[dict]]:
    """Return cached lead list or None if not cached / Redis unavailable."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        key = _places_cache_key("leads", industry, location)
        data = redis_client.get(key)
        if data:
            logger.info(f"[REDIS] Cache HIT  leads:{industry}@{location}")
            return json.loads(data)
    except Exception as e:
        logger.error(f"[REDIS] get_cached_leads error: {e}")
    return None


def set_cached_leads(industry: str, location: str, leads: List[dict], ttl: int = 86400) -> None:
    """Cache lead list for `ttl` seconds (default 24 h)."""
    if not (REDIS_AVAILABLE and redis_client) or not leads:
        return
    try:
        key = _places_cache_key("leads", industry, location)
        redis_client.setex(key, ttl, json.dumps(leads))
        logger.info(f"[REDIS] Cache SET   leads:{industry}@{location} ({len(leads)} leads, ttl={ttl}s)")
    except Exception as e:
        logger.error(f"[REDIS] set_cached_leads error: {e}")


def get_cached_quick_check(industry: str, location: str) -> Optional[bool]:
    """Return cached quick-check result or None."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        key = _places_cache_key("qcheck", industry, location)
        data = redis_client.get(key)
        if data is not None:
            return data == "1"
    except Exception as e:
        logger.error(f"[REDIS] get_cached_quick_check error: {e}")
    return None


def set_cached_quick_check(industry: str, location: str, has_results: bool, ttl: int = 7200) -> None:
    """Cache quick-check boolean for `ttl` seconds (default 2 h)."""
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = _places_cache_key("qcheck", industry, location)
        redis_client.setex(key, ttl, "1" if has_results else "0")
    except Exception as e:
        logger.error(f"[REDIS] set_cached_quick_check error: {e}")


def get_cached_geocode(location: str) -> Optional[tuple]:
    """Return cached (lat, lng, city_radius_km) for a location string, or None."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        # v3: Places Text Search fallback when Geocode only returns a province
        # (Lumbini → Lumbini Province). Older geo: / geo:v2: keys are ignored.
        key = f"geo:v3:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        data = redis_client.get(key)
        if data:
            parsed = json.loads(data)
            if len(parsed) == 3:
                lat, lng, city_radius_km = parsed
                return float(lat), float(lng), float(city_radius_km)
            # legacy cache entry (lat, lng only) — treat as no cache
        return None
    except Exception as e:
        logger.error(f"[REDIS] get_cached_geocode error: {e}")
    return None


def set_cached_geocode(location: str, lat: float, lng: float, city_radius_km: float, ttl: int = 604800) -> None:
    """Cache geocode result + city radius for `ttl` seconds (default 7 days)."""
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = f"geo:v3:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        redis_client.setex(key, ttl, json.dumps([lat, lng, city_radius_km]))
    except Exception as e:
        logger.error(f"[REDIS] set_cached_geocode error: {e}")


def acquire_search_lock(industry: str, location: str, ttl: int = 60) -> bool:
    """
    Try to acquire a distributed lock for a given (industry, location) search.
    Returns True if lock was acquired (this process should do the work),
    False if another process already holds the lock.
    """
    if not (REDIS_AVAILABLE and redis_client):
        return True  # No Redis → always proceed
    try:
        key = _places_cache_key("lock", industry, location)
        # SET NX EX: set only if not exists, with expiry
        acquired = redis_client.set(key, "1", nx=True, ex=ttl)
        return bool(acquired)
    except Exception as e:
        logger.error(f"[REDIS] acquire_search_lock error: {e}")
        return True


def release_search_lock(industry: str, location: str) -> None:
    """Release the distributed search lock."""
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = _places_cache_key("lock", industry, location)
        redis_client.delete(key)
    except Exception as e:
        logger.error(f"[REDIS] release_search_lock error: {e}")


def get_cached_country_check(location: str) -> Optional[bool]:
    """Return cached is_country result or None. TTL 7 days — country names are stable."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        key = f"isctry:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        data = redis_client.get(key)
        if data is not None:
            return data == "1"
    except Exception as e:
        logger.error(f"[REDIS] get_cached_country_check error: {e}")
    return None


def set_cached_country_check(location: str, is_country: bool, ttl: int = 604800) -> None:
    """Cache is_country boolean for `ttl` seconds (default 7 days)."""
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = f"isctry:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        redis_client.setex(key, ttl, "1" if is_country else "0")
    except Exception as e:
        logger.error(f"[REDIS] set_cached_country_check error: {e}")


def get_cached_region_check(location: str) -> Optional[bool]:
    """Return cached is_broad_region result or None. TTL 7 days. Uses 'isrgn:' prefix (separate from country check)."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        key = f"isrgn:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        data = redis_client.get(key)
        if data is not None:
            return data == "1"
    except Exception as e:
        logger.error(f"[REDIS] get_cached_region_check error: {e}")
    return None


def set_cached_region_check(location: str, is_broad: bool, ttl: int = 604800) -> None:
    """Cache is_broad_region boolean for `ttl` seconds (default 7 days)."""
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = f"isrgn:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        redis_client.setex(key, ttl, "1" if is_broad else "0")
    except Exception as e:
        logger.error(f"[REDIS] set_cached_region_check error: {e}")


_PLACE_KIND_VALUES = frozenset({"city", "broad_region", "unresolved"})


def get_cached_place_kind(location: str) -> Optional[str]:
    """Return cached map classification: city | broad_region | unresolved."""
    if not (REDIS_AVAILABLE and redis_client):
        return None
    try:
        key = f"plckind:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        data = redis_client.get(key)
        if data is None:
            return None
        kind = str(data)
        return kind if kind in _PLACE_KIND_VALUES else None
    except Exception as e:
        logger.error(f"[REDIS] get_cached_place_kind error: {e}")
    return None


def set_cached_place_kind(location: str, kind: str, ttl: int = 604800) -> None:
    """Cache map classification for `ttl` seconds (default 7 days)."""
    if kind not in _PLACE_KIND_VALUES:
        return
    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        key = f"plckind:{hashlib.md5(location.strip().lower().encode()).hexdigest()[:12]}"
        # Unresolved misses: shorter TTL so typos can be retried after correction.
        use_ttl = 86400 if kind == "unresolved" else ttl
        redis_client.setex(key, use_ttl, kind)
    except Exception as e:
        logger.error(f"[REDIS] set_cached_place_kind error: {e}")


# ── Per-user Google API rate limiting ────────────────────────────────────────
# Counts only cache-MISS searches (the ones that actually cost money).
# Cache hits are always free and never counted.
#
# When Redis is unavailable the in-memory fallback (_mem_rate) is used so that
# cost protections remain active even during Redis outages.

import time as _time
import threading as _threading

USER_SEARCH_LIMIT = 10   # max fresh API searches per user per hour
USER_SEARCH_WINDOW = 3600  # 1 hour in seconds

# In-memory fallback: {user_id: [(timestamp, count), ...]}
_mem_rate: Dict[str, list] = {}
_mem_rate_lock = _threading.Lock()


def _mem_check_and_increment(user_id: str, increment: bool) -> tuple[bool, int]:
    """Thread-safe in-memory rate check/increment used when Redis is down."""
    now = _time.time()
    cutoff = now - USER_SEARCH_WINDOW
    with _mem_rate_lock:
        entries = _mem_rate.get(user_id, [])
        # Evict expired entries
        entries = [(ts, c) for ts, c in entries if ts > cutoff]
        used = sum(c for _, c in entries)
        allowed = used < USER_SEARCH_LIMIT
        if increment and allowed:
            entries.append((now, 1))
            used += 1
        _mem_rate[user_id] = entries
    remaining = max(USER_SEARCH_LIMIT - used, 0)
    return allowed, remaining


def check_user_search_rate(user_id: str) -> tuple[bool, int]:
    """
    Check if the user is within their hourly fresh-search quota.
    Returns (allowed: bool, remaining: int).
    Falls back to in-memory tracking when Redis is unavailable so that
    cost protections stay active during Redis outages.
    """
    if not (REDIS_AVAILABLE and redis_client):
        return _mem_check_and_increment(user_id, increment=False)
    try:
        key = f"search_rate:{user_id}"
        count = redis_client.get(key)
        used = int(count) if count else 0
        remaining = max(USER_SEARCH_LIMIT - used, 0)
        return used < USER_SEARCH_LIMIT, remaining
    except Exception as e:
        logger.error(f"[REDIS] check_user_search_rate error: {e} — falling back to memory")
        return _mem_check_and_increment(user_id, increment=False)


def increment_user_search_rate(user_id: str) -> int:
    """
    Increment the user's fresh-search counter.
    Returns the new count. Falls back to in-memory when Redis is unavailable.
    """
    if not (REDIS_AVAILABLE and redis_client):
        _, _ = _mem_check_and_increment(user_id, increment=True)
        return sum(c for _, c in _mem_rate.get(user_id, []))
    try:
        key = f"search_rate:{user_id}"
        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, USER_SEARCH_WINDOW)
        results = pipe.execute()
        return results[0]
    except Exception as e:
        logger.error(f"[REDIS] increment_user_search_rate error: {e} — falling back to memory")
        _mem_check_and_increment(user_id, increment=True)
        return sum(c for _, c in _mem_rate.get(user_id, []))
