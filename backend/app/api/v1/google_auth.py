import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_session
from app.core.config import get_settings
from app.services.google_auth_service import handle_google_callback
from fastapi.responses import RedirectResponse

logger = logging.getLogger(__name__)

# router = APIRouter(prefix="/auth/google", tags=["Auth - Google"])
router = APIRouter(prefix="/auth/google", tags=["Auth - Google"])
settings = get_settings()




@router.get("/login")
async def google_login(request: Request):
    """
    Step 1: Returns the Google OAuth 2.0 URL that the frontend or user can open.
    """
    state = secrets.token_urlsafe(32)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={settings.GOOGLE_CLIENT_ID}"
        f"&redirect_uri={settings.GOOGLE_REDIRECT_URI}"
        "&response_type=code"
        "&scope=openid%20email%20profile"
        "&access_type=offline"
        "&prompt=select_account"
        f"&state={state}"
    )
    is_secure = (
        "localhost" not in settings.GOOGLE_REDIRECT_URI
        and "127.0.0.1" not in settings.GOOGLE_REDIRECT_URI
    )
    response = RedirectResponse(url=auth_url)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=is_secure,
    )
    return response


@router.get("/callback")
async def google_callback(
    request: Request,
    code: str = Query(..., description="Authorization code returned from Google"),
    state: str = Query(None, description="CSRF state token"),
    session: AsyncSession = Depends(get_session),
):
    """
    Step 2: Handles the Google redirect callback and completes login/signup.
    """
    # Verify CSRF state token
    expected_state = request.cookies.get("oauth_state")
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        frontend_url = settings.FRONTEND_URL
        request_url = str(request.url)
        response = await handle_google_callback(
            session,
            code,
            frontend_url,
            request_url,
            device_trust_token=request.cookies.get("admin_device_trust"),
        )
        response.delete_cookie("oauth_state")
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Google OAuth callback failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")
    