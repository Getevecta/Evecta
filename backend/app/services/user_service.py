from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from typing import Optional
from fastapi import HTTPException, status
from app.models.user import User
from app.models.role import Role
from app.models.refresh_token import RefreshToken
from app.utils.jwt import hash_password, verify_password, validate_password_not_email
from datetime import datetime, timezone
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError


async def get_available_username(session: AsyncSession, preferred: str) -> str:
    """
    Sanitize OAuth/Google-derived username. Multiple users may share the same username; email is unique.
    """
    base = (preferred or "user").strip()
    base = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:100] or "user"
    return base


# CREATE USER (REGISTER)
async def register_user(
    session: AsyncSession,
    email: str,
    password: Optional[str] = None,
    username: Optional[str] = None,
    role_id: Optional[str] = None,
) -> User:
    """
    Create a new user with hashed password using pure SQLAlchemy async.

    Automatically assigns the default 'user' role if none is specified.
    """

    email = email.strip().lower()

    # Check if user already exists by email
    existing_user = await get_user_by_email(session, email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )

    # Validate password doesn't contain email or email domains
    if password:
        is_valid, error_message = validate_password_not_email(password, email)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message,
            )

    # Hash password securely
    hashed_password = hash_password(password) if password else None

    # Assign default role if not provided
    if not role_id:
        result = await session.execute(select(Role).where(Role.name == "user"))
        default_role = result.scalar_one_or_none()
        if default_role:
            role_id = default_role.id
        else:
            # Graceful fallback: create default role if missing
            new_role = Role(name="user", description="Default user role")
            session.add(new_role)
            await session.flush()  # flush ensures we get the ID
            role_id = new_role.id

    # Create user instance
    user = User(
        email=email,
        username=username,
        hashed_password=hashed_password,
        is_active=True,
        email_verified=False,  # New users need email verification
        created_at=datetime.now(timezone.utc),
        role_id=role_id,
    )

    session.add(user)

    try:
        # flush to get user.id without committing — caller commits
        # after OTP creation so user + OTP succeed or fail together
        await session.flush()
        await session.refresh(user)

        return user

    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user. Please try again.",
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create user. Please try again.",
        )


# GET USER BY EMAIL
async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    """
    Retrieve user by email using SQLAlchemy select().
    """
    try:
        result = await session.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not look up that account. Please try again.",
        )


# GET USER BY ID
async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    """
    Retrieve user by ID using SQLAlchemy select().
    """
    try:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not look up that account. Please try again.",
        )


async def update_user_profile(
    session: AsyncSession,
    user_id: str,
    username: Optional[str] = None,
    email: Optional[str] = None,
    full_name: Optional[str] = None,
    department: Optional[str] = None,
    location: Optional[str] = None,
    website: Optional[str] = None,
    bio: Optional[str] = None,
    profile_image: Optional[str] = None,
) -> User:
    """
    Update user profile information.
    """
    # Fetch user
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Update username if provided
    if username is not None:
        username = username.strip()
        if username and username != user.username:
            user.username = username

    # Email is not editable via profile update
    if email is not None and email.strip().lower() != user.email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email cannot be changed through profile update"
        )

    # Update profile fields if provided (including empty strings to clear them)
    if full_name is not None:
        # Allow empty strings to clear the field
        user.full_name = full_name.strip() if full_name and full_name.strip() else None
    if department is not None:
        user.department = department.strip() if department and department.strip() else None
    if location is not None:
        user.location = location.strip() if location and location.strip() else None
    if website is not None:
        user.website = website.strip() if website and website.strip() else None
    if bio is not None:
        user.bio = bio.strip() if bio and bio.strip() else None
    if profile_image is not None:
        # Allow empty strings to clear the field
        user.profile_image = profile_image.strip() if profile_image and profile_image.strip() else None

    # Update updated_at timestamp
    user.updated_at = datetime.now(timezone.utc)

    try:
        await session.commit()
        await session.refresh(user)
        return user
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A database error occurred. Please try again."
        )
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile. Please try again."
        )


async def update_user_role(session: AsyncSession, user_id: str, role_id: str) -> User:
    """
    Assign or update a user's role.
    Only callable by admin/superuser (router enforces access).
    """
    from app.services.admin_bootstrap import SOLE_ADMIN_EMAIL

    # Fetch user
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Fetch role
    role = await session.get(Role, role_id)
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Role not found"
        )

    if (role.name or "").lower() == "admin":
        if (user.email or "").strip().lower() != SOLE_ADMIN_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only {SOLE_ADMIN_EMAIL} may hold the admin role.",
            )

    # Assign new role
    user.role_id = role_id
    try:
        await session.commit()
        await session.refresh(user)
        return user
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user role. Please try again."
        )


async def get_all_users_with_roles(
    session: AsyncSession,
    *,
    limit: int = 100,
    offset: int = 0,
):
    """
    Retrieve users along with their roles (for admin panel).
    Bounded pagination — never hydrates the full users table in one query.
    """
    try:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        total = await session.scalar(select(func.count(User.id))) or 0
        result = await session.execute(
            select(User)
            .options(selectinload(User.role_obj))
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        users = result.scalars().unique().all()
        return users, int(total), limit, offset
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load users. Please try again.",
        )


async def change_user_password(
    session: AsyncSession,
    user_id: str,
    current_password: str,
    new_password: str,
) -> User:
    """
    Change user password after verifying current password.
    """
    # Fetch user
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Check if user has a password (Google users might not have one)
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password change not available for this account type"
        )

    # Verify current password
    if not verify_password(current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Validate new password doesn't contain email or email domains
    is_valid, error_message = validate_password_not_email(new_password, user.email)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Hash new password
    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(timezone.utc)

    # Revoke all existing refresh tokens — forces re-login on all devices
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )

    try:
        await session.commit()
        await session.refresh(user)
        return user
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password. Please try again."
        )


async def reset_password_with_otp(
    session: AsyncSession,
    email: str,
    new_password: str
) -> User:
    """
    Reset user password after OTP verification.
    """
    # Fetch user
    user = await get_user_by_email(session, email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Validate new password
    is_valid, error_message = validate_password_not_email(new_password, user.email)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message,
        )

    # Hash new password
    user.hashed_password = hash_password(new_password)
    user.updated_at = datetime.now(timezone.utc)

    # If the user was previously unverified, mark them as verified now
    # since they just verified their email with OTP
    user.email_verified = True

    # Revoke all existing refresh tokens — forces re-login on all devices
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked == False)
        .values(revoked=True)
    )

    try:
        await session.commit()
        await session.refresh(user)
        return user
    except Exception as e:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password. Please try again."
        )


async def admin_create_user(
    session: AsyncSession,
    full_name: str,
    email: str,
    username: str,
    password: str,
    role_id: str,
    is_active: bool = True
) -> User:
    """
    Create a new user by admin.
    - No OTP
    - Email auto-verified
    - Admin selects role + status
    """

    try:
        email = email.strip().lower()
        username = username.strip() if username else None

        # 1. Check Email Already Exists
        try:
            existing = await get_user_by_email(session, email)
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="A database error occurred. Please try again."
            )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists"
            )

        # 2. Enforce password policy (same rules as self-registration)
        if password:
            is_valid, error_message = validate_password_not_email(password, email)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_message,
                )

        # 3. Validate Role
        try:
            result_role = await session.execute(
                select(Role).where(Role.id == role_id)
            )
            role = result_role.scalar_one_or_none()
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="A database error occurred. Please try again."
            )

        if not role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invalid role ID"
            )

        from app.services.admin_bootstrap import SOLE_ADMIN_EMAIL

        if (role.name or "").lower() == "admin" and email != SOLE_ADMIN_EMAIL:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only {SOLE_ADMIN_EMAIL} may hold the admin role.",
            )

        # 4. Hash Password
        try:
            hashed_password = hash_password(password)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not process password. Please try again."
            )

        # 5. Create User
        user = User(
            full_name=full_name,
            username=username,
            email=email,
            hashed_password=hashed_password,
            role_id=role_id,
            is_active=is_active,
            email_verified=True,  # Admin-created accounts skip verification
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        session.add(user)

        # Commit + Refresh
        try:
            await session.commit()
            await session.refresh(user)
            return user

        except IntegrityError as e:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="A database error occurred. Please try again."
            )

        except SQLAlchemyError as e:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="A database error occurred. Please try again."
            )

        except Exception as e:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Something went wrong. Please try again."
            )

    except HTTPException:
        raise  # rethrow cleanly

    except Exception as e:
        # fallback catch-all
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again."
        )