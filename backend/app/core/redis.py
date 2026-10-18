import logging
from redis.asyncio import Redis
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_redis: Redis | None = None


async def init_redis() -> None:
    global _redis
    _redis = Redis.from_url(settings.redis_cache_url, decode_responses=True)
    try:
        await _redis.ping()
    except Exception as e:
        logger.error("Redis connection failed: %s", e)
        _redis = None
        raise


async def close_redis() -> None:
    
    if _redis:
        await _redis.close()


def get_redis() -> Redis:
    
    if _redis is None:
        raise RuntimeError("Redis has not been initialized")
    return _redis
