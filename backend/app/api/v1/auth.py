import logging
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Response,
    Request,
    BackgroundTasks
)

logger = logging.getLogger(__name__)
from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession
from app.database.session import get_session
from app.models.user import User
from app.services.auth_service import (
    login_user,
    refresh_access_token,
    logout_user,
    begin_admin_login_2fa,
    complete_admin_login_2fa,
    resend_admin_login_2fa,
)
from app.services.waitlist_service import add_to_waitlist_if_full, get_waitlist_status
from app.services.user_service import (
    register_user, 
    update_user_profile, 
    change_user_password,
    get_user_by_email,
    reset_password_with_otp
) 
from app.services.otp_service import create_otp, send_otp_email, verify_otp
from app.schemas.auth import (
    LoginRequest, 
    TokenResponse,
    AdminLogin2FAVerifyRequest,
    AdminLogin2FAResendRequest,
    ForgotPasswordRequest, 
    ResetPasswordRequest,
    VerifyOTPRequest
)
from app.schemas.user import UserCreate, UserRead, UserUpdate, PasswordChange
from app.dependencies.auth import get_current_user
from app.core.limiter import limiter
from app.core.config import get_settings
from app.services.admin_device_trust import (
    ADMIN_DEVICE_TRUST_COOKIE,
    ADMIN_DEVICE_TRUST_SECONDS,
)
from app.services.session_service import (
    clear_auth_cookies,
    client_ip_from_request,
    cookie_secure,
    set_auth_cookies,
)

settings = get_settings()

router = APIRouter(prefix="/auth", tags=["Authentication"])

_RESET_OTP_GENERIC = "Invalid or expired code."


# REGISTER
@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Register a new user")
@limiter.limit("5/hour")
async def register(
    request: Request,
    data: UserCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    Register a new user account.

    - Validates uniqueness of email
    - Hashes password before storing
    - Creates OTP for email verification
    - Sends OTP to user's email
    - Returns created user data
    """

    try:
        waitlisted = await add_to_waitlist_if_full(session, data.email, data.username)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add to waitlist. Please try again."
        )

    if waitlisted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "WAITLISTED",
                "message": "Registration is full. You’ve been added to the waitlist."
            }
        )

    try:
        logger.info(f"📥 Received registration request for email: {data.email}, username: {data.username}")

        # If account exists but email is not verified, resend OTP instead of rejecting
        existing = await get_user_by_email(session, data.email.strip().lower())
        if existing and not existing.email_verified:
            otp_result = await create_otp(session, str(existing.id), existing.email, expires_minutes=30)
            background_tasks.add_task(send_otp_email, existing.email, otp_result.plaintext_code)
            logger.info(f"🔁 Resent OTP for unverified account: {existing.email}")
            return existing

        if existing and existing.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An account with this email already exists. Please sign in.",
            )

        user = await register_user(session, data.email, data.password, data.username)

        # Create OTP — this commits both user + OTP in one transaction.
        # If OTP creation fails, user is also rolled back (no orphaned users).
        otp_result = await create_otp(session, str(user.id), data.email, expires_minutes=30)

        # Grant free plan credits (all pools) after user + OTP are committed.
        # Never fail registration over the bonus — repair_missing_free_signup_grant
        # (credit_service) backfills it on the user's next balance read.
        from app.services.credit_service import grant_plan_credits
        from app.core.plans import PLANS, DEFAULT_PLAN
        try:
            await grant_plan_credits(session, user.id, PLANS[DEFAULT_PLAN]["credits"], "Free plan signup bonus")
        except Exception:
            await session.rollback()
            logger.exception(f"❌ Signup credit grant failed (will self-heal on next balance read) | user={user.id}")

        # Send OTP email in background to avoid timeouts
        background_tasks.add_task(send_otp_email, data.email, otp_result.plaintext_code)

        logger.info(f"✅ Registration successful for {data.email}")
        return user
    except HTTPException:
        # Re-raise HTTPExceptions (like existing user errors from register_user)
        raise
    except Exception as e:
        error_str = str(e)
        logger.error(f"❌ Registration error: {e}")
        
        # Handle duplicate key errors
        if "duplicate key value violates unique constraint" in error_str or "UniqueViolationError" in error_str:
            if "email" in error_str.lower() or "ix_users_email" in error_str.lower():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already exists"
                )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again."
        )


# LOGIN
@router.post("/login", response_model=TokenResponse, summary="Authenticate user and issue tokens")
@limiter.limit("10/minute")
async def login(
    request: Request,
    data: LoginRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """
    Authenticate the user with email and password.

    - Regular users: access + refresh tokens (refresh in HttpOnly cookie)
    - Admin: OTP on first/new device; trusted devices skip OTP for 15 days
    """
    device_trust = request.cookies.get(ADMIN_DEVICE_TRUST_COOKIE)
    result = await login_user(
        session,
        data.email,
        data.password,
        device_trust_token=device_trust,
        client_ip=client_ip_from_request(request),
    )

    if result.get("requires_2fa"):
        plaintext = await begin_admin_login_2fa(
            session,
            user_id=result["user_id"],
            email=result["email"],
        )
        background_tasks.add_task(send_otp_email, result["email"], plaintext)
        return TokenResponse(
            access_token=None,
            requires_2fa=True,
            email=result["email"],
            message=result.get("message"),
        )

    is_https = request.url.scheme == 'https'
    secure = cookie_secure(is_https)
    refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600
    if result.get("device_trusted"):
        refresh_max_age = ADMIN_DEVICE_TRUST_SECONDS

    set_auth_cookies(
        response,
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        secure=secure,
        refresh_max_age=refresh_max_age,
        # Keep existing trust cookie as-is when already trusted (still valid in Redis)
    )
    return TokenResponse(access_token=result["access_token"], token_type="bearer")


@router.post(
    "/login/verify-2fa",
    response_model=TokenResponse,
    summary="Complete admin login with email OTP",
)
@limiter.limit("10/minute")
async def login_verify_2fa(
    request: Request,
    data: AdminLogin2FAVerifyRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Verify the OTP emailed after admin password login, then issue tokens + device trust."""
    tokens = await complete_admin_login_2fa(session, data.email, data.otp_code)

    is_https = request.url.scheme == "https"
    set_auth_cookies(
        response,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        secure=cookie_secure(is_https),
        refresh_max_age=ADMIN_DEVICE_TRUST_SECONDS,
        device_trust_token=tokens.get("device_trust_token"),
    )
    return TokenResponse(access_token=tokens["access_token"], token_type="bearer")


@router.post(
    "/login/resend-2fa",
    summary="Resend admin login OTP",
)
@limiter.limit("5/minute")
async def login_resend_2fa(
    request: Request,
    data: AdminLogin2FAResendRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Resend OTP only if the password step already succeeded for this email."""
    plaintext = await resend_admin_login_2fa(session, data.email)
    background_tasks.add_task(send_otp_email, data.email, plaintext)
    return {
        "status": "success",
        "message": "A new verification code was sent to your email.",
    }


# REFRESH TOKEN
@router.post("/refresh", response_model=TokenResponse, summary="Refresh access token using HttpOnly cookie")
@limiter.limit("30/minute")
async def refresh_token(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    """
    Refresh the user's access token using the HttpOnly refresh cookie.

    - Reads refresh token from cookie
    - Validates it and issues new access token
    - Sets new access token as HttpOnly cookie
    """
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing"
        )

    new_tokens = await refresh_access_token(session, refresh_token)

    is_https = request.url.scheme == 'https'
    set_auth_cookies(
        response,
        access_token=new_tokens["access_token"],
        refresh_token=new_tokens["refresh_token"],
        secure=cookie_secure(is_https),
    )

    return new_tokens


# LOGOUT
@router.post("/logout", status_code=status.HTTP_200_OK, summary="Logout user and revoke refresh token")
async def logout(response: Response, request: Request, session: AsyncSession = Depends(get_session)):
    """
    Logout user and revoke their active refresh token.

    - Reads refresh token from cookie
    - Revokes it from database
    - Clears refresh cookie from browser
    """
    refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        try:
            await logout_user(session, refresh_token)
        except HTTPException:
            # Cookie may already be expired or revoked; still clear the browser session.
            pass

    # Always clear cookies and return 200 so the client can complete logout even if the
    # refresh cookie was already missing (e.g. cleared by the browser) or expired.
    # Keep admin_device_trust so password-only re-login works on this device for 15 days.
    clear_auth_cookies(
        response,
        secure=cookie_secure(request.url.scheme == "https"),
    )

    return {"detail": "Successfully logged out."}


@router.patch("/me", response_model=UserRead, summary="Update current user profile")
async def update_current_user(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Update the current user's profile information.
    """
    updated_user = await update_user_profile(
        session=session,
        user_id=str(current_user.id),
        username=data.username,
        email=data.email,
        full_name=data.full_name,
        department=data.department,
        location=data.location,
        website=data.website,
        bio=data.bio,
        profile_image=data.profile_image
    )
    return updated_user


@router.post("/forgot-password", summary="Send OTP for password reset")
@limiter.limit("5/hour")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    Initiate password reset process by sending OTP to user's email.
    """
    user = await get_user_by_email(session, data.email)
    if not user:
        # For security reasons, don't reveal if user exists or not
        return {"message": "If an account exists with this email, an OTP has been sent."}

    otp_result = await create_otp(session, str(user.id), data.email, expires_minutes=30)

    # Send OTP email in background to avoid timeouts
    background_tasks.add_task(send_otp_email, data.email, otp_result.plaintext_code)
    
    return {"message": "Verification code sent! Please check your inbox"}


@router.post("/verify-reset-otp", summary="Verify OTP for password reset")
@limiter.limit("10/hour")
async def verify_reset_otp(
    request: Request,
    data: VerifyOTPRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Verify if the OTP matches for the given email.
    """
    user = await get_user_by_email(session, data.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )

    try:
        is_valid = await verify_otp(session, str(user.id), data.otp_code, mark_as_used=False)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )

    return {"message": "OTP verified successfully. You can now reset your password."}


@router.post("/reset-password", summary="Reset password using OTP")
@limiter.limit("5/hour")
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Reset user password after OTP verification.
    """
    user = await get_user_by_email(session, data.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )

    try:
        is_valid = await verify_otp(session, str(user.id), data.otp_code, mark_as_used=False)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_RESET_OTP_GENERIC,
        )

    # Reset password (complexity checks happen here)
    await reset_password_with_otp(
        session=session,
        email=data.email,
        new_password=data.new_password
    )

    # Only mark as used AFTER successful password update
    await verify_otp(session, str(user.id), data.otp_code, mark_as_used=True)

    return {"message": "Password reset successfully. You can now login with your new password."}


@router.get("/me")
async def read_current_user(current_user: User = Depends(get_current_user)):
    """
    Example protected endpoint — only accessible with a valid access token.
    Returns basic user info including creation date and role.
    """
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "first_login_at": current_user.first_login_at.isoformat() if current_user.first_login_at else None,
        "last_login_at": current_user.last_login_at.isoformat() if current_user.last_login_at else None,
        "full_name": current_user.full_name,
        "department": current_user.department,
        "location": current_user.location,
        "website": current_user.website,
        "bio": current_user.bio,
        "profile_image": current_user.profile_image,
        "email_sending_mode": (
            current_user.email_sending_mode.value
            if current_user.email_sending_mode
            else None
        ),
        "role": current_user.role_obj.name if current_user.role_obj else None,
        "is_admin": bool(
            current_user.is_superuser
            or (current_user.role_obj and current_user.role_obj.name == "admin")
        ),
    }


@router.get("/waitlist-status")
async def check_waitlist_status(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Check if the current logged-in user is on the waitlist.
    Returns waitlist status and total user count.
    Only users who registered AFTER the first 100 users should be waitlisted.
    The first 100 users (by created_at, with id as tiebreaker) always have access.
    """
    return await get_waitlist_status(session, current_user)


@router.patch("/me/password", response_model=UserRead, summary="Change user password")
async def change_password(
    data: PasswordChange,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Change the current user's password.
    Requires current password verification.
    """
    updated_user = await change_user_password(
        session=session,
        user_id=str(current_user.id),
        current_password=data.current_password,
        new_password=data.new_password
    )
    return updated_user