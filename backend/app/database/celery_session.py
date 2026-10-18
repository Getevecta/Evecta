import os
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_settings

settings = get_settings()


if os.name == "nt":  # Windows
    celery_async_engine = create_async_engine(
        settings.async_database_url,
        pool_pre_ping=False,  # asyncpg + pool_pre_ping causes MissingGreenlet in Celery workers
        poolclass=NullPool,   # no connection reuse across event loops
    )
else:
    celery_async_engine = create_async_engine(
        settings.async_database_url,
        pool_pre_ping=False,  # asyncpg + pool_pre_ping causes MissingGreenlet in Celery workers
        pool_size=5,
        max_overflow=0,
        pool_recycle=1800,
    )

celery_session_factory = async_sessionmaker(
    celery_async_engine,
    expire_on_commit=False,
)
