from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from pydantic import EmailStr
from sqlalchemy.ext.asyncio.session import AsyncSession
from app.database.session import get_session
from app.services.otp_service import (
    create_otp, 
    verify_otp, 
    can_resend_otp, 
    send_otp_email,
    get_otp_by_user_id
)
from app.services.user_service import get_user_by_email
from app.schemas.otp import (
    OTPRequest, 
    OTPVerificationRequest, 
    OTPResponse, 
    OTPVerificationResponse
)
from app.core.limiter import limiter
from app.services.session_service import cookie_secure, establish_session
from datetime import datetime, timezone

router = APIRouter(prefix="/otp", tags=["OTP Verification"])


@router.post("/send", response_model=OTPResponse, summary="Send OTP to email")
@limiter.limit("4/hour")
async def send_otp(
    request: Request,
    body: OTPRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session)
):
    """
    Send OTP code to user's email for verification.
    
    - Checks if user exists
    - Creates new OTP with 10-minute expiration
    - Sends email with OTP code
    - Returns success message with expiration info
    """
    # Check if user exists — always return generic response to prevent email enumeration
    user = await get_user_by_email(session, body.email)
    if not user:
        return OTPResponse(
            message="If an account exists for this email, an OTP has been sent.",
            can_resend_in=60
        )

    # Check if user can resend OTP (cooldown)
    if not await can_resend_otp(session, str(user.id), cooldown_minutes=1):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before requesting another OTP"
        )

    otp_result = await create_otp(session, str(user.id), body.email, expires_minutes=10)

    # Send email in background to avoid timeouts
    background_tasks.add_task(send_otp_email, body.email, otp_result.plaintext_code)

    return OTPResponse(
        message="If an account exists for this email, an OTP has been sent.",
        expires_at=otp_result.otp.expires_at,
        can_resend_in=60
    )


@router.post("/verify", response_model=OTPVerificationResponse, summary="Verify OTP code")
async def verify_otp_code(
    request: OTPVerificationRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Verify the OTP code entered by user.
    
    - Validates OTP code
    - Marks user's email as verified
    - Returns success status
    """
    # This endpoint should be called with user context
    # For now, we'll need the user_id from the request or session
    # In a real implementation, you might get this from JWT token or session
    
    # For now, we'll return an error asking for user_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="User ID required for OTP verification"
    )


@router.post("/verify/{user_id}", response_model=OTPVerificationResponse, summary="Verify OTP code for user")
@limiter.limit("5/hour")
async def verify_otp_for_user(
    request: Request,
    user_id: str,
    body: OTPVerificationRequest,
    session: AsyncSession = Depends(get_session)
):
    """
    Verify the OTP code for a specific user.
    Email must match the user_id to prevent account takeover.
    """
    try:
        # Cross-check: verify that the email in the request matches the user_id
        # This prevents an attacker from targeting arbitrary user_ids
        user = await get_user_by_email(session, body.email.strip().lower())
        if not user or str(user.id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid OTP code. Please try again."
            )

        is_valid = await verify_otp(session, user_id, body.code)
        
        if is_valid:
            payload = OTPVerificationResponse(
                success=True,
                message="Email verified successfully! You are now logged in.",
                user_id=user_id,
                token_type="bearer",
            ).model_dump(exclude_none=True)
            response = JSONResponse(content=payload)
            await establish_session(
                session,
                response,
                user_id,
                secure=cookie_secure(request.url.scheme == "https"),
            )
            return response
        else:
            return OTPVerificationResponse(
                success=False,
                message="Invalid OTP code. Please try again."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification failed. Please try again."
        )


@router.get("/status/{user_id}", response_model=OTPResponse, summary="Check OTP status")
@limiter.limit("10/minute")
async def check_otp_status(
    request: Request,
    user_id: str,
    email: EmailStr = Query(...),
    session: AsyncSession = Depends(get_session)
):
    """
    Check the status of the latest OTP for a user.

    Caller must prove ownership with the account email (same as /otp/verify).
    """
    user = await get_user_by_email(session, email.strip().lower())
    if not user or str(user.id) != user_id:
        return OTPResponse(message="If an OTP exists for this account, it is still valid.")

    otp = await get_otp_by_user_id(session, user_id)
    
    if not otp:
        return OTPResponse(
            message="If an OTP exists for this account, it is still valid."
        )
    
    can_resend = await can_resend_otp(session, user_id, cooldown_minutes=1)
    time_until_resend = 0
    
    if not can_resend:
        time_since_creation = datetime.now(timezone.utc) - otp.created_at
        time_until_resend = max(0, 60 - int(time_since_creation.total_seconds()))
    
    return OTPResponse(
        message="OTP status retrieved",
        expires_at=otp.expires_at,
        can_resend_in=time_until_resend
    )
