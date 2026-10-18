"""Admin role bootstrap + sole-admin enforcement.

The only platform admin mailbox is ``SOLE_ADMIN_EMAIL``. On startup, every other
superuser / admin-role account is demoted to a normal user.

Passwords are never read from .env or source code. Create/reset the sole admin with:

    cd backend && python -m scripts.create_admin --email evecta.evecta@gmail.com

Only a bcrypt hash is stored in ``users.hashed_password``.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.role import Role
from app.models.user import User
from app.utils.jwt import hash_password, is_bcrypt_hash, validate_password_not_email

logger = logging.getLogger(__name__)

# Single real admin — no other account may keep admin / superuser privileges.
SOLE_ADMIN_EMAIL = "evecta.evecta@gmail.com"

# Former admins that must stay demoted and force-logged-out on every boot.
FORMER_ADMIN_EMAILS = frozenset({"sushma@evecta.io"})


async def _ensure_role(session: AsyncSession, name: str, description: str) -> Role:
    result = await session.execute(select(Role).where(Role.name == name))
    role = result.scalar_one_or_none()
    if role is not None:
        return role

    try:
        async with session.begin_nested():
            role = Role(name=name, description=description)
            session.add(role)
            await session.flush()
        logger.info("Created '%s' role", name)
        return role
    except IntegrityError:
        # Another gunicorn worker created the role concurrently.
        result = await session.execute(select(Role).where(Role.name == name))
        role = result.scalar_one_or_none()
        if role is None:
            raise RuntimeError(f"Failed to ensure role '{name}' after concurrent create")
        return role


async def _force_logout_user(session: AsyncSession, user_id) -> int:
    """Revoke every refresh token for ``user_id`` (same transaction; no nested commit)."""
    from app.models.refresh_token import RefreshToken
    from sqlalchemy import update

    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .where(RefreshToken.revoked.is_(False))
        .values(revoked=True)
    )
    return result.rowcount or 0


async def enforce_sole_admin(session: AsyncSession) -> None:
    """
    Demote every admin/superuser except ``SOLE_ADMIN_EMAIL``.
    Promote the sole admin mailbox if it already exists.
    Former admins (e.g. sushma@evecta.io) are demoted and force-logged-out.
    """
    admin_role = await _ensure_role(session, "admin", "Platform administrator")
    user_role = await _ensure_role(session, "user", "Standard user")
    sole = SOLE_ADMIN_EMAIL.strip().lower()
    former = {e.strip().lower() for e in FORMER_ADMIN_EMAILS}

    result = await session.execute(
        select(User)
        .options(selectinload(User.role_obj))
        .where(
            or_(
                User.is_superuser.is_(True),
                User.role_id == admin_role.id,
                func.lower(User.email) == sole,
                func.lower(User.email).in_(former),
            )
        )
    )
    users = result.scalars().all()
    changed = False

    for user in users:
        email = (user.email or "").strip().lower()
        if email == sole:
            if not user.is_superuser:
                user.is_superuser = True
                changed = True
            if user.role_id != admin_role.id:
                user.role_id = admin_role.id
                changed = True
            if not user.is_active:
                user.is_active = True
                changed = True
            if not user.email_verified:
                user.email_verified = True
                changed = True
            continue

        # Anyone else holding admin privileges → normal user + kill sessions
        demoted = False
        if user.is_superuser:
            user.is_superuser = False
            demoted = True
        if user.role_id == admin_role.id:
            user.role_id = user_role.id
            demoted = True

        if email in former:
            # Former admins must not sign in at all (staging/prod).
            if user.role_id != user_role.id:
                user.role_id = user_role.id
                demoted = True
            if user.is_active:
                user.is_active = False
                demoted = True
            revoked = await _force_logout_user(session, user.id)
            changed = True
            logger.info(
                "Disabled former admin %s (active=False, revoked %s refresh token(s))",
                email,
                revoked,
            )
        elif demoted:
            revoked = await _force_logout_user(session, user.id)
            changed = True
            logger.info(
                "Demoted non-sole admin %s to role=user (revoked %s refresh token(s))",
                email,
                revoked,
            )

    if changed:
        await session.commit()
        logger.info("Sole admin enforced: %s", sole)
    else:
        logger.info("Sole admin already enforced: %s", sole)


async def ensure_admin_user(session: AsyncSession) -> None:
    """
    Startup hook: ensure roles exist, then enforce a single admin mailbox.
    Does not create credentials — use ``python -m scripts.create_admin``.
    """
    await _ensure_role(session, "admin", "Platform administrator")
    await _ensure_role(session, "user", "Standard user")
    await enforce_sole_admin(session)


def resolve_password_hash(*, password: str, admin_email: str) -> str:
    """Validate plaintext once, return bcrypt hash. Never log ``password``."""
    ok, err = validate_password_not_email(password, admin_email)
    if not ok:
        raise ValueError(err or "Password failed complexity checks")
    return hash_password(password)


async def create_or_update_admin(
    session: AsyncSession,
    *,
    email: str,
    username: str | None,
    password: str | None = None,
    password_hash: str | None = None,
    reset_password: bool = False,
) -> tuple[User, str]:
    """
    Create or update the sole admin account only.

    ``email`` must be ``SOLE_ADMIN_EMAIL``. Other addresses are rejected so
    former admins cannot be re-promoted via this path.
    """
    admin_email = email.strip().lower()
    if admin_email != SOLE_ADMIN_EMAIL:
        raise ValueError(
            f"Only {SOLE_ADMIN_EMAIL} may be the platform admin "
            f"(refusing {admin_email})."
        )

    stored_hash: str | None = None
    if password_hash:
        if not is_bcrypt_hash(password_hash):
            raise ValueError("password_hash must be a valid bcrypt hash ($2b$...)")
        stored_hash = password_hash.strip()
    elif password:
        stored_hash = resolve_password_hash(password=password, admin_email=admin_email)

    admin_role = await _ensure_role(session, "admin", "Platform administrator")
    await _ensure_role(session, "user", "Standard user")

    result = await session.execute(
        select(User).where(func.lower(User.email) == admin_email)
    )
    existing = result.scalar_one_or_none()

    if existing:
        action = "promoted"
        existing.is_superuser = True
        existing.role_id = admin_role.id
        existing.is_active = True
        existing.email_verified = True
        if username:
            existing.username = username.strip()[:100]
        if reset_password:
            if not stored_hash:
                raise ValueError("Password required when --reset-password is set")
            existing.hashed_password = stored_hash
            action = "password_reset"
        await session.commit()
        await session.refresh(existing)
        await enforce_sole_admin(session)
        logger.info("Admin account updated for %s (action=%s)", admin_email, action)
        return existing, action

    if not stored_hash:
        raise ValueError("Password required to create a new admin account")

    uname = (username or "").strip() or admin_email.split("@")[0]
    admin = User(
        email=admin_email,
        username=uname[:100],
        hashed_password=stored_hash,
        is_active=True,
        is_superuser=True,
        email_verified=True,
        role_id=admin_role.id,
        full_name="Administrator",
    )
    session.add(admin)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        result = await session.execute(
            select(User).where(func.lower(User.email) == admin_email)
        )
        raced = result.scalar_one_or_none()
        if raced is None:
            raise
        return await create_or_update_admin(
            session,
            email=admin_email,
            username=username,
            password=password,
            password_hash=password_hash,
            reset_password=reset_password,
        )

    await session.refresh(admin)
    await enforce_sole_admin(session)
    logger.info("Created admin user %s (password stored as bcrypt only)", admin_email)
    return admin, "created"
