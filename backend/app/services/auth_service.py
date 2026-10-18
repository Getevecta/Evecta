from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
from app.models.user import User
from app.utils.jwt import (
    decode_token,
    verify_password,
    hash_password,
    get_dummy_password_hash,
)
from app.services.user_service import get_user_by_email
from app.services.session_service import issue_session
from app.services.token_service import (
    is_refresh_token_valid,
    revoke_refresh_token,
)

_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_LOCKOUT_SECONDS = 15 * 60  # 15 minutes
_ADMIN_2FA_PENDING_TTL = 10 * 60  # 10 minutes after password OK


def _login_lockout_key(email: str, ip: str) -> str:
    """Lockout is per email+IP so a third party cannot lock a known account globally."""
    return f"login_lockout:{email.lower()}:{ip or 'unknown'}"


def _login_attempts_key(email: str, ip: str) -> str:
    return f"login_attempts:{email.lower()}:{ip or 'unknown'}"


def _admin_2fa_pending_key(email: str) -> str:
    return f"admin_2fa_pending:{email.lower()}"


def user_requires_login_2fa(user: User) -> bool:
    """Email OTP after password is required only for the sole admin mailbox."""
    from app.services.admin_bootstrap import SOLE_ADMIN_EMAIL

    email = (user.email or "").strip().lower()
    return email == SOLE_ADMIN_EMAIL.strip().lower()


async def get_user_by_email_with_role(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(
        select(User)
        .options(selectinload(User.role_obj))
        .where(func.lower(User.email) == email.strip().lower())
    )
    return result.scalar_one_or_none()


async def _issue_login_tokens(
    session: AsyncSession,
    user: User,
    *,
    refresh_expire_days: int | None = None,
) -> dict:
    """Record login timestamps and issue access + refresh tokens."""
    if user.first_login_at is None:
        user.first_login_at = datetime.now(timezone.utc)
        user.last_login_at = datetime.now(timezone.utc)
    else:
        user.last_login_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(user)

    return await issue_session(
        session,
        user.id,
        refresh_expire_days=refresh_expire_days,
    )


# LOGIN USER
async def login_user(
    session: AsyncSession,
    email: str,
    password: str,
    *,
    device_trust_token: str | None = None,
    client_ip: str = "unknown",
) -> dict:
    """
    Authenticate user credentials.

    Regular users receive JWT tokens immediately.
    Admin mailbox: OTP on first login / new device; trusted devices skip OTP
    for 15 days (then must OTP again).
    """
    from app.core.redis import get_redis
    from app.services.admin_device_trust import (
        ADMIN_DEVICE_TRUST_DAYS,
        validate_admin_device_trust,
    )

    redis = get_redis()
    lockout_key = _login_lockout_key(email, client_ip)
    attempts_key = _login_attempts_key(email, client_ip)

    # Check if account is currently locked out
    if await redis.exists(lockout_key):
        ttl = await redis.ttl(lockout_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {ttl // 60 + 1} minute(s).",
        )

    # Fetch user from DB (with role for admin 2FA check)
    user = await get_user_by_email_with_role(session, email)

    # Always run bcrypt — even when user doesn't exist — so response time is
    # identical whether the email is registered or not (prevents enumeration via timing).
    password_ok = verify_password(
        password,
        user.hashed_password if user and user.hashed_password else get_dummy_password_hash(),
    )

    if not user or not password_ok:
        # Increment failed attempts; lock account after threshold
        attempts = await redis.incr(attempts_key)
        await redis.expire(attempts_key, _LOGIN_LOCKOUT_SECONDS)
        if attempts >= _LOGIN_MAX_ATTEMPTS:
            await redis.set(lockout_key, "1", ex=_LOGIN_LOCKOUT_SECONDS)
            await redis.delete(attempts_key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    # Successful password — clear any failed attempt counters
    await redis.delete(attempts_key, lockout_key)

    from app.services.admin_bootstrap import FORMER_ADMIN_EMAILS

    if (user.email or "").strip().lower() in {e.lower() for e in FORMER_ADMIN_EMAILS}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is no longer allowed to sign in. Use the admin account instead.",
        )

    # Check if user active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )

    # Check if email is verified
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in.",
        )

    if user_requires_login_2fa(user):
        trusted = await validate_admin_device_trust(device_trust_token, str(user.id))
        if trusted:
            tokens = await _issue_login_tokens(
                session,
                user,
                refresh_expire_days=ADMIN_DEVICE_TRUST_DAYS,
            )
            tokens["device_trusted"] = True
            return tokens

        # Password OK — do not issue tokens yet. Mark pending 2FA in Redis.
        await redis.set(
            _admin_2fa_pending_key(user.email),
            str(user.id),
            ex=_ADMIN_2FA_PENDING_TTL,
        )
        return {
            "requires_2fa": True,
            "email": user.email,
            "user_id": str(user.id),
            "token_type": "bearer",
            "message": "Enter the verification code sent to your email to finish signing in.",
        }

    return await _issue_login_tokens(session, user)


async def begin_admin_login_2fa(session: AsyncSession, user_id: str, email: str) -> str:
    """Create a fresh OTP for an admin mid-login. Returns plaintext code for email send."""
    from app.services.otp_service import create_otp

    otp_result = await create_otp(session, user_id, email, expires_minutes=10)
    return otp_result.plaintext_code


async def complete_admin_login_2fa(
    session: AsyncSession,
    email: str,
    otp_code: str,
) -> dict:
    """
    Verify email OTP after admin password login, then issue tokens + device trust.
    Requires a live ``admin_2fa_pending`` Redis marker from ``login_user``.
    """
    from app.core.redis import get_redis
    from app.services.otp_service import verify_otp
    from app.services.admin_device_trust import (
        ADMIN_DEVICE_TRUST_DAYS,
        create_admin_device_trust,
    )

    redis = get_redis()
    pending_key = _admin_2fa_pending_key(email)
    pending_user_id = await redis.get(pending_key)
    if not pending_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login session expired. Please sign in again.",
        )
    if isinstance(pending_user_id, bytes):
        pending_user_id = pending_user_id.decode()

    user = await get_user_by_email_with_role(session, email)
    if not user or str(user.id) != str(pending_user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login session expired. Please sign in again.",
        )
    if not user_requires_login_2fa(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Two-factor verification is only required for admin accounts.",
        )

    is_valid = await verify_otp(session, str(user.id), otp_code, mark_as_used=True)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code.",
        )

    await redis.delete(pending_key)
    tokens = await _issue_login_tokens(
        session,
        user,
        refresh_expire_days=ADMIN_DEVICE_TRUST_DAYS,
    )
    tokens["device_trust_token"] = await create_admin_device_trust(str(user.id))
    return tokens


async def resend_admin_login_2fa(session: AsyncSession, email: str) -> str:
    """Resend OTP only if password step already succeeded (pending Redis key)."""
    from app.core.redis import get_redis
    from app.services.otp_service import create_otp, can_resend_otp

    redis = get_redis()
    pending_key = _admin_2fa_pending_key(email)
    pending_user_id = await redis.get(pending_key)
    if not pending_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login session expired. Please sign in again.",
        )
    if isinstance(pending_user_id, bytes):
        pending_user_id = pending_user_id.decode()

    user = await get_user_by_email_with_role(session, email)
    if not user or str(user.id) != str(pending_user_id) or not user_requires_login_2fa(user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login session expired. Please sign in again.",
        )

    if not await can_resend_otp(session, str(user.id), cooldown_minutes=1):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before requesting another code.",
        )

    # Refresh pending TTL so the session doesn't expire mid-resend
    await redis.set(pending_key, str(user.id), ex=_ADMIN_2FA_PENDING_TTL)
    otp_result = await create_otp(session, str(user.id), user.email, expires_minutes=10)
    return otp_result.plaintext_code


# REFRESH ACCESS TOKEN
async def refresh_access_token(session: AsyncSession, refresh_token_str: str) -> dict:
    """
    Validates a refresh token and issues a new access token.
    """

    # Decode token
    try:
        payload = decode_token(refresh_token_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    # Reject access tokens (or any non-refresh tokens) used in the refresh flow
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Refresh token required.",
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    if not user_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed refresh token payload.",
        )

    # Verify if the token record is valid and not revoked
    valid = await is_refresh_token_valid(session, user_id, jti)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalid, expired, or revoked.",
        )

    # Rotate: revoke old refresh token and issue a new one
    await revoke_refresh_token(session, user_id, jti)
    return await issue_session(session, user_id)


# LOGOUT USER
async def logout_user(session: AsyncSession, refresh_token_str: str) -> dict:
    """
    Revokes a given refresh token, effectively logging out the user.
    """

    # Decode token payload
    try:
        payload = decode_token(refresh_token_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
        )

    user_id = payload.get("sub")
    jti = payload.get("jti")

    if not user_id or not jti:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed refresh token payload.",
        )

    # Revoke the refresh token in DB
    revoked = await revoke_refresh_token(session, user_id, jti)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found or already revoked.",
        )

    return {"detail": "Logout successful. Refresh token revoked."}
