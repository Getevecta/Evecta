import asyncio
import logging
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_celery_engine():
    """
    Create a FRESH async engine for THIS Celery task only.

    Always use NullPool: each task creates and disposes its own engine, so a
    QueuePool is wasted and dangerous — concurrent tasks used to open
    pool_size=50 (+ overflow) connections each and exhaust Postgres
    (TooManyConnectionsError), which then 500s admin pages like AI Usage.
    """
    logger.info("[CELERY_ENGINE] Creating NullPool engine (per-task)")
    return create_async_engine(
        settings.async_database_url,
        pool_pre_ping=True,
        poolclass=NullPool,
    )


def get_celery_session_factory():
    """
    Create a FRESH session factory for THIS Celery task only.
    Returns both the factory and the engine (you need both to dispose).
    
    Returns:
        tuple: (session_factory, engine)
    """
    engine = get_celery_engine()
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    return session_factory, engine


def cleanup_event_loop(loop, engine):
    """
    Properly clean up event loop and engine.
    Call this in the finally block of Celery tasks.
    
    Steps:
    1. Dispose engine (close all connections)
    2. Cancel pending tasks
    3. Close event loop
    """
    # STEP 1: Dispose the engine
    try:
        logger.info("[CLEANUP] Disposing async engine...")
        loop.run_until_complete(engine.dispose())
        logger.info("[CLEANUP] ✅ Async engine disposed successfully")
    except Exception as e:
        logger.error(f"[CLEANUP] ❌ Error disposing async engine: {e}", exc_info=True)
    
    # STEP 2: Cancel any pending tasks
    try:
        pending = asyncio.all_tasks(loop)
        if pending:
            logger.warning(f"[CLEANUP] Found {len(pending)} pending tasks, cancelling...")
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            logger.info("[CLEANUP] ✅ Pending tasks cancelled")
    except Exception as e:
        logger.error(f"[CLEANUP] ❌ Error cleaning up pending tasks: {e}")
    
    # STEP 3: Close the loop
    try:
        loop.close()
        logger.info("[CLEANUP] ✅ Event loop closed successfully")
    except Exception as e:
        logger.error(f"[CLEANUP] ❌ Error closing event loop: {e}")