import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from app.database.session import async_session_factory
from app.services.email_rotation_service import reset_daily_counters


async def main():
    async with async_session_factory() as session:
        await reset_daily_counters(session)


if __name__ == "__main__":
    logger.info("Cron started at %s", datetime.now(timezone.utc))
    asyncio.run(main())
