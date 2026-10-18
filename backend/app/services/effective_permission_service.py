from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.permission import Permission
from sqlalchemy.exc import SQLAlchemyError
from app.services.permission_service import (
    calculate_final_permissions,
    grouped_permissions_from_final,
)


async def get_effective_permissions(session: AsyncSession, user_id: str):
    """Grouped permission view for the admin UI.

    Grant decisions come from calculate_final_permissions (same function as the
    route guard), not a second merge of role + overrides.
    """
    try:
        from app.dependencies.auth import load_user_with_permissions

        try:
            user = await load_user_with_permissions(session, user_id)
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while loading user"
            )

        if not user:
            return None

        final = getattr(user, "final_permissions", None)
        if final is None:
            final = calculate_final_permissions(user)

        try:
            result = await session.execute(select(Permission))
            all_permissions = result.scalars().all()
        except SQLAlchemyError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database error while loading permissions"
            )

        try:
            return grouped_permissions_from_final(all_permissions, final)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error building effective permissions structure"
            )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )
