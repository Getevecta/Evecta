import logging
import os
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import text
from typing import AsyncGenerator
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Load settings once (cached)
settings = get_settings()


def running_in_celery_process(argv: list[str] | None = None) -> bool:
    """True when this process was started by the `celery` command (worker / beat)."""
    argv = sys.argv if argv is None else argv
    if not argv:
        return False
    first = argv[0].replace("\\", "/")
    return os.path.basename(first).lower().startswith("celery") or first.endswith("celery/__main__.py")


if running_in_celery_process():
    # Each Celery task runs in its own event loop and closes it afterwards. Pooled
    # asyncpg connections stay bound to the loop that opened them, so a later task
    # reusing one fails ("attached to a different loop", "Event loop is closed").
    # Code reached from tasks through this shared factory (AI/API usage tracking,
    # status logging) therefore opens a fresh connection per session instead.
    engine = create_async_engine(
        settings.async_database_url,
        echo=False,
        future=True,
        poolclass=NullPool,
    )
else:
    # Create async engine (PostgreSQL + asyncpg)
    engine = create_async_engine(
        settings.async_database_url,
        echo=False,           # Set True for SQL query logs in dev
        future=True,          # SQLAlchemy 2.0 style
        pool_pre_ping=True,   # Checks if connections are alive before use
        pool_size=5,          # Persistent connections kept in pool (per API process)
        max_overflow=10,      # Extra connections allowed under burst load
        pool_timeout=30,      # Seconds to wait for a connection before error
        pool_recycle=1800,    # Recycle connections after 30 min (avoids stale TCP)
    )

# Async session factory
async_session_factory = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# Dependency for FastAPI routes
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides an async SQLAlchemy session for FastAPI dependency injection.
    Ensures proper cleanup after request.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# Database connection health check
async def check_connection() -> bool:
    """
    Tests if the database connection is alive.
    Returns True if connected, False otherwise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error("Database connection check failed: %s", e, exc_info=True)
        return False
