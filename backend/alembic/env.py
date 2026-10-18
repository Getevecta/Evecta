import asyncio
from logging.config import fileConfig
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import pool

from geoalchemy2 import alembic_helpers

from app.core.config import get_settings
from app.database.base import Base
import app.models

settings = get_settings()
config = context.config
fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", settings.async_database_url)

target_metadata = Base.metadata

# PostGIS creates these system tables/views when the extension is enabled.
# They are NOT in our models — without this filter, autogenerate emits DROP
# statements for them and breaks PostGIS.
_POSTGIS_MANAGED = {
    "spatial_ref_sys", "geometry_columns", "geography_columns",
    "raster_columns", "raster_overviews", "topology", "layer",
}


def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table" and name in _POSTGIS_MANAGED:
        return False  # never let Alembic manage PostGIS system tables
    # delegate to GeoAlchemy2 so it ignores auto-managed spatial indexes
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def run_migrations_offline():
    """Run migrations in 'offline' mode (no live DB connection)."""
    url = settings.async_database_url.replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations in an active connection context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,                      # ignore PostGIS system tables
        render_item=alembic_helpers.render_item,             # render Geometry() columns
        process_revision_directives=alembic_helpers.writer,  # handle spatial indexes
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Run migrations asynchronously using asyncpg."""
    connectable = create_async_engine(
        settings.async_database_url,
        poolclass=pool.NullPool,
        future=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
