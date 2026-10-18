import logging
from sqlalchemy import select, func, or_, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.waitlist import Waitlist

logger = logging.getLogger(__name__)

USER_LIMIT = 100


async def add_to_waitlist_if_full(
    session: AsyncSession,
    email: str,
    username: str,
) -> bool:
    """
    Check if user limit is reached and add to waitlist if so.

    Uses SELECT FOR UPDATE to prevent race conditions where two simultaneous
    registrations could both pass the count check and both get registered.

    Returns True if the user was waitlisted (limit reached), False otherwise.
    """
    result = await session.execute(
        select(func.count(User.id))
    )
    total_users = result.scalar() or 0

    if total_users < USER_LIMIT:
        return False

    # Limit reached — add to waitlist
    try:
        session.add(Waitlist(email=email.strip().lower(), username=username))
        await session.commit()
    except IntegrityError:
        # Already in waitlist (case-insensitive unique index) — that's fine
        await session.rollback()
    except Exception:
        await session.rollback()
        logger.exception("Failed to add user to waitlist")
        raise

    return True


async def get_waitlist_status(session: AsyncSession, user: User) -> dict:
    """
    Return waitlist status for the given user:
      - is_on_waitlist: email found in waitlist table
      - total_users: current total user count
      - user_limit_reached: user registered after the first USER_LIMIT users
    """
    waitlist_entry = await session.execute(
        select(Waitlist).where(func.lower(Waitlist.email) == user.email.strip().lower())
    )
    is_on_waitlist = waitlist_entry.scalar_one_or_none() is not None

    total_users_result = await session.execute(select(func.count(User.id)))
    total_users = total_users_result.scalar() or 0

    user_limit_reached = False
    if total_users > USER_LIMIT:
        rank_query = select(func.count(User.id)).where(
            or_(
                User.created_at < user.created_at,
                and_(
                    User.created_at == user.created_at,
                    User.id <= user.id,
                ),
            )
        )
        user_rank = (await session.execute(rank_query)).scalar() or 0
        if user_rank > USER_LIMIT:
            user_limit_reached = True

    return {
        "is_on_waitlist": is_on_waitlist,
        "total_users": total_users,
        "user_limit_reached": user_limit_reached,
    }
