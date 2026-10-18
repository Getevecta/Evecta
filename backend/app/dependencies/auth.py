from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_session
from app.utils.jwt import decode_token
from app.models.user import User
from sqlalchemy.future import select
from app.models.role import Role
from app.models.permission import Permission
from sqlalchemy.orm import selectinload
from typing import Optional
from fastapi.security.utils import get_authorization_scheme_param
from app.models.user_permission_override import UserPermissionOverride
from app.services.permission_service import (
    calculate_final_permissions,
    enabled_permission_names,
)


# auto_error=False — keeps Swagger Authorize button visible without blocking cookie-based auth
_http_bearer = HTTPBearer(auto_error=False)


async def load_user_with_permissions(session: AsyncSession, user_id) -> Optional[User]:
    """Load a User (role + role permissions + overrides eager-loaded, final_permissions
    computed) bound to the given session. Shared by get_current_user and any caller that
    needs a fresh, attached User on a session of its own (e.g. streaming responses, where
    the request-scoped Depends(get_session) session may already be closed by the time the
    work actually runs)."""
    result = await session.execute(
        select(User)
        .options(
            selectinload(User.role_obj).selectinload(Role.permissions),
            selectinload(User.permission_overrides)
            .selectinload(UserPermissionOverride.permission),
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user:
        user.final_permissions = calculate_final_permissions(user)
    return user


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _bearer: Optional[HTTPAuthorizationCredentials] = Depends(_http_bearer),  # only for Swagger UI lock icon
) -> User:
    """
    Load the user along with role, role permissions, and overrides.
    Reads token from HttpOnly cookie first, falls back to Authorization: Bearer header.
    """
    # Try cookie first (new secure flow)
    token = request.cookies.get("access_token")

    # Fall back to Bearer header (current frontend — until frontend switches)
    if not token:
        authorization = request.headers.get("Authorization")
        scheme, param = get_authorization_scheme_param(authorization)
        if authorization and scheme.lower() == "bearer":
            token = param

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token)
    except ValueError as e:
        # Token decode error (expired, invalid, etc.) - return 401
        error_msg = str(e)
        if "expired" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired. Please log in again.",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token. Please log in again.",
            )

    # Reject refresh tokens (and any other non-access tokens) used as Bearer tokens
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Access token required.",
        )

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID.",
        )

    # Load user + role + role permissions + overrides + override permissions
    user = await load_user_with_permissions(session, user_id)

    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user.")

    return user



async def get_current_user_optional(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    try:
        return await get_current_user(request, session)
    except HTTPException:
        return None

# Role-based guard
def require_role(*allowed_roles: str):
    async def wrapper(current_user: User = Depends(get_current_user)):
        if current_user.is_superuser:
            return current_user
        if not current_user.role_obj or current_user.role_obj.name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role: {allowed_roles}",
            )
        return current_user
    return wrapper

# Permission-based guard
def require_permission(*required_permissions: str):
    """
    Checks final effective permissions (role + overrides, including explicit
    ``is_enabled=False`` revokes). Superusers always pass.
    """

    async def wrapper(
        current_user: User = Depends(get_current_user),
    ):

        # SUPERUSER ALWAYS ALLOWED
        if current_user.is_superuser:
            return current_user

        # Same merge as the UI: calculate_final_permissions on the eager-loaded user.
        # Fail closed if final_permissions was not computed.
        final_enabled = enabled_permission_names(current_user)

        missing = [p for p in required_permissions if p not in final_enabled]

        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission(s): {', '.join(missing)}"
            )

        return current_user

    return wrapper