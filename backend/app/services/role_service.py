from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status
from app.models.role import Role
from app.models.permission import Permission


# CREATE ROLE
async def create_role(session: AsyncSession, name: str, description: str = None) -> Role:
    """
    Create a new role if it doesn't already exist.
    Uses deferred commit for transaction safety.
    """
    try:
        # Check for existing role
        result = await session.execute(select(Role).where(Role.name == name))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Role already exists")

        # Create and stage the new role (no commit yet)
        role = Role(name=name, description=description)
        session.add(role)
        await session.flush()  # assign ID without committing

        await session.refresh(role)
        return role

    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update roles. Please try again.",
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=500, detail="Failed to update roles. Please try again."
        )

# UPDATE ROLE
async def update_role(session: AsyncSession, role_id: str, data):
    result = await session.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    # Update name
    if data.name:
        role.name = data.name

    # Update description
    if data.description:
        role.description = data.description

    await session.flush()

    # Update permissions
    if data.permission_ids is not None:
        await assign_permissions_to_role(session, role_id, data.permission_ids)

    await session.commit()
    await session.refresh(role)
    return role


# DELETE ROLE (HARD DELETE)
async def delete_role(session: AsyncSession, role_id: str):
    result = await session.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()

    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    await session.delete(role)
    await session.commit()

    return {"message": "Role deleted successfully"}
# CREATE PERMISSION
async def create_permission(session: AsyncSession, name: str, description: str = None, group: str = "General"):
    try:
        # Check duplicate
        result = await session.execute(select(Permission).where(Permission.name == name))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Permission already exists")

        perm = Permission(name=name, description=description, group=group)

        session.add(perm)
        await session.commit()
        await session.refresh(perm)

        return perm

    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update permissions. Please try again.",
        )

async def update_permission(session: AsyncSession, permission_id: str, data):
    result = await session.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()

    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    if data.name:
        perm.name = data.name

    if data.description is not None:
        perm.description = data.description

    if data.group is not None:
        perm.group = data.group

    await session.commit()
    await session.refresh(perm)

    return perm


async def delete_permission(session: AsyncSession, permission_id: str):
    result = await session.execute(select(Permission).where(Permission.id == permission_id))
    perm = result.scalar_one_or_none()

    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    await session.delete(perm)
    await session.commit()

    return {"message": "Permission deleted successfully"}



# ASSIGN PERMISSIONS TO ROLE
async def assign_permissions_to_role(
    session: AsyncSession, role_id, permission_ids: list
) -> Role:
    """
    Assign multiple permissions to a role.
    Overwrites existing permission list for that role.
    """
    role = await session.get(Role, role_id, options=[selectinload(Role.permissions)])
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if not permission_ids:
        # Clear permissions if empty list provided
        role.permissions = []
        await session.commit()
        await session.refresh(role)
        return role

    result = await session.execute(
        select(Permission).where(Permission.id.in_(permission_ids))
    )
    perms = result.scalars().all()

    if len(perms) != len(permission_ids):
        raise HTTPException(status_code=404, detail="One or more permissions not found")

    role.permissions = perms
    await session.commit()
    await session.refresh(role)
    return role


# GET ALL ROLES (with permissions preloaded)
async def get_roles(session: AsyncSession):
    """
    Return all roles with their associated permissions.
    Uses selectinload() for async-safe eager loading.
    """
    result = await session.execute(select(Role).options(selectinload(Role.permissions)))
    return result.scalars().unique().all()


# GET ALL PERMISSIONS
async def get_permissions(session: AsyncSession):
    """
    Return all available permissions.
    """
    result = await session.execute(select(Permission))
    return result.scalars().all()


# GROUP PERMISSIONS BY GROUP NAME
async def get_grouped_permissions(session: AsyncSession):
    try:
        result = await session.execute(select(Permission))
        permissions = result.scalars().all()

        grouped = {}

        for perm in permissions:
            group_name = perm.group or "General"
            if group_name not in grouped:
                grouped[group_name] = []

            grouped[group_name].append({
                "id": str(perm.id),
                "name": perm.name,
                "description": perm.description
            })

        return grouped

    except SQLAlchemyError as e:
        # Log if needed
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred. Please try again."
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )
