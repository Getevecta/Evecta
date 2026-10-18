from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException, status
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app.models.user import User
from app.models.permission import Permission
from app.models.user_permission_override import UserPermissionOverride


# GET USER OVERRIDES
async def get_user_overrides(session: AsyncSession, user_id: str):
    """
    Returns a list of permission_ids that are overridden (force-enabled).
    """
    try:
        try:
            result = await session.execute(
                select(UserPermissionOverride.permission_id)
                .where(UserPermissionOverride.user_id == user_id)
            )
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while loading user permission overrides"
            )

        try:
            rows = result.scalars().all()
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing override permission data"
            )

        return [str(pid) for pid in rows]

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )


# UPDATE USER OVERRIDES (ENABLE SPECIFIC PERMISSIONS)
async def update_user_overrides(session: AsyncSession, user_id: str, permission_ids: list[str]):
    """
    Overrides work as:
        - store ON overrides only
        - override OFF = simply not included in the table
    """
    try:
        # STEP 1 — Delete old overrides
        try:
            await session.execute(
                delete(UserPermissionOverride)
                .where(UserPermissionOverride.user_id == user_id)
            )
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while deleting old overrides"
            )

        # STEP 2 — Insert ON overrides
        now = datetime.now(timezone.utc)

        try:
            for pid in permission_ids:
                session.add(
                    UserPermissionOverride(
                        user_id=user_id,
                        permission_id=pid,
                        is_enabled=True,   # REQUIRED
                        created_at=now,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid permission ID(s) provided"
            )
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while inserting overrides"
            )

        # Save changes
        try:
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save user overrides"
            )

        # Return updated overrides
        try:
            return await get_user_overrides(session, user_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error loading updated overrides"
            )

    except HTTPException:
        raise

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )


# CLEAR ALL USER OVERRIDES
async def clear_user_overrides(session: AsyncSession, user_id: str):
    """
    Removes all overrides for a user (user falls back to role defaults only).
    """
    try:
        # Delete overrides
        try:
            await session.execute(
                delete(UserPermissionOverride)
                .where(UserPermissionOverride.user_id == user_id)
            )
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while clearing user overrides"
            )

        # Commit the change
        try:
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to commit override deletion"
            )

        return {"message": "Overrides cleared"}

    except HTTPException:
        raise

    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )
