import httpx
import logging
from fastapi import HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.user import User
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from app.models.waitlist import Waitlist
from app.services.user_service import register_user, get_available_username
from app.core.config import get_settings
from app.services.session_service import cookie_secure, establish_session

logger = logging.getLogger(__name__)

settings = get_settings()

DASHBOARD_PATH = "/dashboard"  # redirect destination


def google_verified_email(user_info: dict) -> str:
    """Return a normalized Google email only when Google marks it verified."""
    email = user_info.get("email")
    if not email or not str(email).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account did not return an email address.",
        )
    verified = user_info.get("email_verified")
    if verified is not True and str(verified).lower() != "true":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google email is not verified. Use a verified Google account.",
        )
    return str(email).strip().lower()


async def handle_google_callback(
    session: AsyncSession,
    code: str,
    frontend_url: str = None,
    request_url: str = None,
    device_trust_token: str = None,
):
    """
    Complete Google OAuth2 login/signup flow securely.
    
    Args:
        session: Database session
        code: Authorization code from Google
        frontend_url: Frontend URL to redirect to (if None, uses settings.FRONTEND_URL)
        device_trust_token: Optional admin device-trust cookie (skip OTP if valid)
    """
    # --- Step 1: Exchange authorization code for Google tokens ---
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(token_url, data=token_data)
        if token_response.status_code != 200:
            logger.error(
                "Google token exchange failed status=%s body=%s",
                token_response.status_code,
                token_response.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google sign-in failed. Please try again.",
            )
        tokens = token_response.json()

    access_token_google = tokens.get("access_token")
    if not access_token_google:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google response missing access_token.",
        )

    # --- Step 2: Retrieve user info from Google ---
    user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    async with httpx.AsyncClient(timeout=10.0) as client:
        user_info_response = await client.get(
            user_info_url,
            headers={"Authorization": f"Bearer {access_token_google}"}
        )

    if user_info_response.status_code != 200:
        logger.error(
            "Google userinfo failed status=%s body=%s",
            user_info_response.status_code,
            user_info_response.text[:500],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google sign-in failed. Please try again.",
        )

    user_info = user_info_response.json()
    email = google_verified_email(user_info)
    username = user_info.get("name") or email.split("@")[0]

    from app.services.admin_bootstrap import FORMER_ADMIN_EMAILS

    if email.strip().lower() in {e.lower() for e in FORMER_ADMIN_EMAILS}:
        if frontend_url is None:
            frontend_url = getattr(settings, "FRONTEND_URL", "https://evecta.io")
        frontend_url = frontend_url.rstrip("/")
        return RedirectResponse(
            url=f"{frontend_url}/auth?error=account_disabled"
        )

    # --- Step 3: Check if user exists ---
    result = await session.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()

    # --- Step 4: Create user if new ---
    if not user:
        total_users = await session.scalar(select(func.count(User.id)))
        if total_users >= 100:
            # Add to waitlist
            try:
                session.add(Waitlist(email=email, username=username))
                await session.commit()
            except IntegrityError:
                await session.rollback()  # already waitlisted
            except Exception:
                await session.rollback()
                raise HTTPException(status_code=500, detail="Failed to add to waitlist")

            # Redirect to frontend waitlist page (better UX for OAuth redirects)
            if frontend_url is None:
                frontend_url = getattr(settings, "FRONTEND_URL", "https://evecta.io")
            frontend_url = frontend_url.rstrip("/")

            return RedirectResponse(url=f"{frontend_url}/waitlist?code=WAITLISTED")
            
        # Only email must be unique for registration. If Google username is already taken,
        # use a unique variant (e.g. append suffix) so the same name can sign up and only email blocks duplicates.
        unique_username = await get_available_username(session, username)
        user = await register_user(
            session=session,
            email=email,
            password=None,  # Google users don't need password
            username=unique_username,
        )
        # Match email/password registration: grant default plan credits for all pools (OAuth had none before).
        # Never fail sign-in over the bonus — repair_missing_free_signup_grant
        # (credit_service) backfills it on the user's next balance read.
        from app.services.credit_service import grant_plan_credits
        from app.core.plans import PLANS, DEFAULT_PLAN

        try:
            await grant_plan_credits(session, user.id, PLANS[DEFAULT_PLAN]["credits"], "Free plan signup bonus (Google)")
        except Exception:
            await session.rollback()
            logger.exception("Signup credit grant failed (will self-heal on next balance read) | user=%s", user.id)

    # --- Step 5: Issue tokens (sole admin must complete email OTP first) ---
    from app.services.auth_service import (
        user_requires_login_2fa,
        begin_admin_login_2fa,
        _admin_2fa_pending_key,
        _ADMIN_2FA_PENDING_TTL,
    )
    from app.core.redis import get_redis
    from app.services.otp_service import send_otp_email
    from urllib.parse import quote

    if frontend_url is None:
        frontend_url = getattr(settings, 'FRONTEND_URL', 'https://evecta.io')

    # Email-only check — do NOT touch user.role_obj (lazy load → greenlet error on AsyncSession)
    if user_requires_login_2fa(user):
        from app.services.admin_device_trust import (
            ADMIN_DEVICE_TRUST_DAYS,
            ADMIN_DEVICE_TRUST_SECONDS,
            validate_admin_device_trust,
        )

        if await validate_admin_device_trust(device_trust_token, str(user.id)):
            callback_url = f"{frontend_url}/auth/google/success"
            response = RedirectResponse(url=callback_url)
            is_https = bool(request_url and request_url.startswith("https://"))
            await establish_session(
                session,
                response,
                user.id,
                secure=cookie_secure(is_https),
                refresh_expire_days=ADMIN_DEVICE_TRUST_DAYS,
                refresh_max_age=ADMIN_DEVICE_TRUST_SECONDS,
                access_samesite="lax",
                refresh_samesite="lax",
            )
            return response

        redis = get_redis()
        await redis.set(
            _admin_2fa_pending_key(user.email),
            str(user.id),
            ex=_ADMIN_2FA_PENDING_TTL,
        )
        plaintext = await begin_admin_login_2fa(session, str(user.id), user.email)
        send_otp_email(user.email, plaintext)
        return RedirectResponse(
            url=f"{frontend_url}/admin-login-2fa?email={quote(user.email)}"
        )

    # --- Step 6: Redirect to frontend callback with session cookies ---
    callback_url = f"{frontend_url}/auth/google/success"
    response = RedirectResponse(url=callback_url)

    is_https = bool(request_url and request_url.startswith("https://"))
    await establish_session(
        session,
        response,
        user.id,
        secure=cookie_secure(is_https),
        access_samesite="lax",
        refresh_samesite="lax",
    )

    return response
  