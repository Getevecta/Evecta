from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.models.refresh_token import RefreshToken
import uuid


# STORE REFRESH TOKEN
async def store_refresh_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    jti: str,
    expires_at: datetime
) -> RefreshToken:
    """
    Store a new refresh token for a user.
    Automatically cleans up expired tokens for the same user.
    """

    try:
        # Delete all expired tokens for the same user (cleanup)
        await session.execute(
            delete(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .where(RefreshToken.expires_at < datetime.now(timezone.utc))
        )

        # Create new token record
        token = RefreshToken(
            user_id=user_id,
            jti=jti,
            expires_at=expires_at,
            revoked=False,
            created_at=datetime.now(timezone.utc)
        )

        session.add(token)
        await session.commit()
        await session.refresh(token)
        return token

    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your session could not be updated. Please sign in again."
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your session could not be updated. Please sign in again."
        )


# VALIDATE REFRESH TOKEN
async def is_refresh_token_valid(
    session: AsyncSession,
    user_id: int,
    jti: str
) -> bool:
    """
    Check if a refresh token exists, is not revoked, and not expired.
    """

    try:
        result = await session.execute(
            select(RefreshToken).where(
                (RefreshToken.user_id == user_id)
                & (RefreshToken.jti == jti)
                & (RefreshToken.revoked == False)  # noqa
            )
        )
        token = result.scalar_one_or_none()
        if not token:
            return False

        # Auto revoke if expired
        if token.expires_at < datetime.now(timezone.utc):
            token.revoked = True
            await session.commit()
            return False

        return True

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your session could not be updated. Please sign in again."
        )


# REVOKE SINGLE REFRESH TOKEN
async def revoke_refresh_token(
    session: AsyncSession,
    user_id: str,   # UUID-safe typing (string form)
    jti: str
) -> bool:
    """
    Revokes a specific refresh token.
    Works for both local and Google OAuth users.
    Returns True if token was successfully revoked, else False.
    """

    try:
        result = await session.execute(
            select(RefreshToken).where(
                (RefreshToken.user_id == user_id) & (RefreshToken.jti == jti)
            )
        )
        token = result.scalar_one_or_none()

        if not token:
            # Token not found in DB
            return False

        if token.revoked:
            # Already revoked
            return False

        token.revoked = True
        await session.commit()
        return True

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your session could not be updated. Please sign in again."
        )


# -------------------------------
# REVOKE ALL USER TOKENS
# -------------------------------
async def revoke_all_user_tokens(
    session: AsyncSession,
    user_id: uuid.UUID | str,
    *,
    commit: bool = True,
) -> int:
    """
    Revoke all refresh tokens for a given user.
    Useful for disable, global logout, or compromised accounts.
    Returns number of tokens revoked.
    """

    try:
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .values(revoked=True)
            .execution_options(synchronize_session="fetch")
        )
        result = await session.execute(stmt)
        if commit:
            await session.commit()
        return result.rowcount or 0

    except Exception:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your session could not be updated. Please sign in again."
        )
