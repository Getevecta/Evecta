from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.dependencies.auth import require_role, require_permission
from app.database.session import get_session
from app.schemas.role import (
    RoleCreate, RoleRead,
    PermissionCreate, PermissionRead, RoleUpdate, PermissionUpdate
)
from app.services.role_service import (
    create_role,
    create_permission,
    assign_permissions_to_role,
    get_roles,
    get_permissions,
    update_role,
    delete_role,
    update_permission,
    delete_permission
)
from app.models.role import Role
from pydantic import BaseModel
from typing import List

from app.models.user import User

class AssignPermissionsBody(BaseModel):
    permission_ids: List[str]

router = APIRouter(prefix="/roles", tags=["Roles & Permissions"])


# CREATE ROLE
@router.post("/", response_model=RoleRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("manage_roles"))])
async def create_role_api(
    data: RoleCreate, session: AsyncSession = Depends(get_session)
):
    """
    Create a new role and optionally assign permissions to it.
    Automatically re-fetches role with permissions preloaded.
    """

    # Create the role (no commit issues due to flush)
    role = await create_role(session, data.name, data.description)

    # Assign permissions (if provided)
    if data.permission_ids:
        role = await assign_permissions_to_role(session, role.id, data.permission_ids)
    else:
        # Explicitly commit role if no permissions assigned
        await session.commit()

    # Re-fetch role with permissions eager loaded
    result = await session.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.id == role.id)
    )
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found after creation")

    return role


# LIST ROLES
@router.get("/", response_model=list[RoleRead], dependencies=[Depends(require_role("admin"))])
async def list_roles_api(session: AsyncSession = Depends(get_session)):
    return await get_roles(session)

# UPDATE ROLE
@router.patch("/{role_id}", response_model=RoleRead, dependencies=[Depends(require_permission("manage_roles"))])
async def update_role_api(role_id: str, data: RoleUpdate, session: AsyncSession = Depends(get_session)):
    role = await update_role(session, role_id, data)

    result = await session.execute(
        select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
    )
    return result.scalar_one()


# DELETE ROLE (HARD DELETE)
@router.delete("/{role_id}", dependencies=[Depends(require_permission("manage_roles"))])
async def delete_role_api(role_id: str, session: AsyncSession = Depends(get_session)):
    return await delete_role(session, role_id)

# CREATE PERMISSION
@router.post("/permissions", response_model=PermissionRead, dependencies=[Depends(require_permission("manage_permissions"))])
async def create_permission_api(data: PermissionCreate, session: AsyncSession = Depends(get_session)):
    return await create_permission(session, data.name, data.description, data.group)


# LIST PERMISSIONS
@router.get("/permissions", response_model=list[PermissionRead], dependencies=[Depends(require_role("admin"))])
async def list_permissions_api(session: AsyncSession = Depends(get_session)):
    """
    Fetch all available permissions.
    """
    return await get_permissions(session)

@router.patch("/permissions/{permission_id}", response_model=PermissionRead, dependencies=[Depends(require_permission("manage_permissions"))])
async def update_permission_api(permission_id: str, data: PermissionUpdate, session: AsyncSession = Depends(get_session)):
    return await update_permission(session, permission_id, data)

@router.delete("/permissions/{permission_id}", dependencies=[Depends(require_permission("manage_permissions"))])
async def delete_permission_api(permission_id: str, session: AsyncSession = Depends(get_session)):
    return await delete_permission(session, permission_id)

# ASSIGN PERMISSIONS TO ROLE
@router.post("/{role_id}/assign", response_model=RoleRead, dependencies=[Depends(require_permission("manage_roles"))])
async def assign_permissions_api(
    role_id: str,
    data: AssignPermissionsBody,
    session: AsyncSession = Depends(get_session),
):
    """
    Assign one or more permissions to a role.
    Accepts JSON body like:
    {
        "permission_ids": ["uuid1", "uuid2"]
    }
    """
    role = await assign_permissions_to_role(session, role_id, data.permission_ids)

    # Re-fetch role with permissions eagerly loaded to prevent async lazy-load errors
    result = await session.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.id == role.id)
    )
    role = result.scalar_one_or_none()

    return role

@router.get("/permissions/grouped", dependencies=[Depends(require_role("admin"))])
async def list_grouped_permissions_api(session: AsyncSession = Depends(get_session)):
    """
    Returns permissions grouped by category:
    {
        "Users": [...],
        "Posts": [...],
        "General": [...]
    }
    """
    from app.services.role_service import get_grouped_permissions
    return await get_grouped_permissions(session)


@router.get("/{role_id}", response_model=RoleRead)
async def get_role_by_id_api(
    role_id: str,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_role("admin"))
):

    result = await session.execute(
        select(Role)
        .options(selectinload(Role.permissions))
        .where(Role.id == role_id)
    )
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    return role
