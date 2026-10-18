from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_session
from app.services.user_service import update_user_role, admin_create_user
from app.dependencies.auth import require_role, require_permission
from app.schemas.user import UserRead, UserList, UserListPage
from app.services.user_service import get_all_users_with_roles
from app.services.permission_override_service import (
    get_user_overrides,
    update_user_overrides,
    clear_user_overrides,
)
from app.schemas.user import AdminUserCreate, AdminUserUpdate, AdminUserPlanUpdate
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.services.effective_permission_service import get_effective_permissions
from app.models.user import User
from pydantic import BaseModel

from app.models.role import Role
from app.services.admin_user_service import admin_set_user_plan


router = APIRouter(prefix="/users", tags=["Users"])

@router.patch("/{user_id}/role", dependencies=[Depends(require_role("admin"))])
async def update_user_role_api(
    user_id: str,
    role_id: str,
    session: AsyncSession = Depends(get_session)
):
    """
    Update or assign a role to a user (admin-only).
    """
    user = await update_user_role(session, user_id, role_id)
    return {
        "message": f"Role updated successfully for {user.email}",
        "new_role_id": str(user.role_id)
    }


@router.patch("/{user_id}/plan", dependencies=[Depends(require_role("admin"))])
async def update_user_plan_api(
    user_id: str,
    data: AdminUserPlanUpdate,
    session: AsyncSession = Depends(get_session),
):
    """
    Admin complimentary plan change (upgrade / downgrade / free).
    Adjusts subscription credit buckets; does not open Stripe Checkout.
    """
    return await admin_set_user_plan(
        session,
        user_id,
        data.plan,
        data.plan_billing_interval,
    )


@router.get("/", response_model=UserListPage, dependencies=[Depends(require_role("admin"))])
async def list_all_users_api(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    List users with plan, signup, and login metadata (admin-only).
    Paginated; max 200 rows per request.
    """
    users, total, limit, offset = await get_all_users_with_roles(
        session, limit=limit, offset=offset
    )
    items = [
        UserList(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            is_active=bool(u.is_active),
            is_superuser=bool(u.is_superuser),
            email_verified=bool(getattr(u, "email_verified", False)),
            created_at=u.created_at,
            updated_at=u.updated_at,
            plan=(u.plan or "free").strip().lower(),
            plan_billing_interval=getattr(u, "plan_billing_interval", None),
            first_login_at=getattr(u, "first_login_at", None),
            last_login_at=getattr(u, "last_login_at", None),
            role_obj=u.role_obj,
        )
        for u in users
    ]
    return UserListPage(items=items, total=total, limit=limit, offset=offset)

@router.get("/{user_id}/permissions/overrides")
async def fetch_user_overrides(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):
    return await get_user_overrides(session, user_id)


class OverrideUpdateRequest(BaseModel):
    permission_ids: list[str]


@router.patch("/{user_id}/permissions/overrides")
async def update_user_permission_overrides(
    user_id: str,
    data: OverrideUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin"))
):
    updated = await update_user_overrides(session, user_id, data.permission_ids)
    return {"overrides": updated}

@router.delete("/{user_id}/permissions/overrides")
async def delete_user_overrides(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):
    return await clear_user_overrides(session, user_id)


@router.get("/{user_id}/permissions/effective")
async def get_effective_permissions_api(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):
    result = await get_effective_permissions(session, user_id)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.post("/{user_id}/permissions/reset")
async def reset_user_permissions_to_defaults(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):
    # Clear all overrides
    await clear_user_overrides(session, user_id)

    # Return new effective permissions (role defaults only)
    from app.services.effective_permission_service import get_effective_permissions
    updated = await get_effective_permissions(session, user_id)

    return {
        "message": "User permissions reset to role defaults.",
        "effective_permissions": updated
    }


@router.post("/create", dependencies=[Depends(require_role("admin"))])
async def create_user_admin_api(
    data: AdminUserCreate,
    session: AsyncSession = Depends(get_session)
):
    """
    Admin creates a user with:
    - Full name, email, username
    - Password
    - Role assignment
    - Active/Inactive status
    - Permission overrides (optional)
    """

    # Create user with selected role & state
    user = await admin_create_user(
        session=session,
        full_name=data.full_name,
        email=data.email,
        username=data.username,
        password=data.password,
        role_id=str(data.role_id),
        is_active=data.is_active,
    )

    # Apply permission overrides (if provided)
    if data.override_permission_ids and len(data.override_permission_ids) > 0:
        from app.services.permission_override_service import update_user_overrides
        await update_user_overrides(
            session=session,
            user_id=str(user.id),
            permission_ids=[str(pid) for pid in data.override_permission_ids]
        )

    # Calculate final effective permissions (role + overrides)
    effective_permissions = await get_effective_permissions(session, str(user.id))

    return {
        "message": "User created successfully",
        "user": UserRead.model_validate(user),
        "effective_permissions": effective_permissions
    }

@router.get("/{user_id}/details")
async def get_user_details(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):
    """
    Fetch full user details:
    - basic profile
    - role info
    - role permissions
    - overrides
    - effective permissions
    """
    # Load user
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.role_obj).selectinload(Role.permissions)
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Load overrides
    from app.services.permission_override_service import get_user_overrides
    overrides = await get_user_overrides(session, user_id)

    # Load effective permissions
    from app.services.effective_permission_service import get_effective_permissions
    effective = await get_effective_permissions(session, user_id)

    # Build role permissions
    role_perms = []
    if user.role_obj:
        for perm in user.role_obj.permissions:
            role_perms.append({
                "id": str(perm.id),
                "name": perm.name,
                "description": perm.description,
            })

    # Response
    return {
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            "username": user.username,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "department": user.department,
            "location": user.location,
            "website": user.website,
            "bio": user.bio,
            "profile_image": user.profile_image
        },
        "role": {
            "id": str(user.role_obj.id) if user.role_obj else None,
            "name": user.role_obj.name if user.role_obj else None,
            "permissions": role_perms
        },
        "overrides": overrides,
        "effective_permissions": effective
    }

@router.patch("/{user_id}", dependencies=[Depends(require_role("admin"))])
async def update_user_api(
    user_id: str,
    data: AdminUserUpdate,
    session: AsyncSession = Depends(get_session)
):
    from app.services.admin_user_service import admin_update_user

    updated_user, effective_permissions = await admin_update_user(
        session=session,
        user_id=user_id,
        data=data
    )

    return {
        "message": "User updated successfully",
        "user": updated_user,
        "effective_permissions": effective_permissions
    }


@router.delete("/{user_id}/hard", dependencies=[Depends(require_permission("hard_delete_user"))])
async def hard_delete_user_api(
    user_id: str,
    session: AsyncSession = Depends(get_session)
):
    from app.services.admin_user_service import admin_hard_delete_user

    return await admin_hard_delete_user(session, user_id)
