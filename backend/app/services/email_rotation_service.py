import logging
from datetime import datetime, timezone
from sqlalchemy import update

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.models.domain import Domain
from app.models.mailbox import Mailbox


# RESET DAILY COUNTERS (Run via CRON every midnight)
async def reset_daily_counters(session: AsyncSession):
    """
    Resets the sent counts for domains and mailboxes.
    To be executed in a scheduled cron job at midnight.
    """

    now = datetime.now(timezone.utc)

    # Only allow reset between 00:00 - 00:10 so it cannot run multiple times accidentally
    if not (now.hour == 0 and now.minute < 10):
        return  # ignore accidental calls

    try:
        # Reset domain counters
        await session.execute(
            update(Domain).values(sent_today=0)
        )

        # Reset mailbox counters
        await session.execute(
            update(Mailbox).values(sent_today=0)
        )

        await session.commit()

    except SQLAlchemyError as e:
        await session.rollback()
        logger.error("Error resetting counters: %s", e)
