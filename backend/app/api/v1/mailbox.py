import logging
import secrets
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse, RedirectResponse
from urllib.parse import quote, urlencode

from app.database.session import get_session
from app.schemas.mailbox import EmailSendingModeUpdate, MailboxCreate, MailboxRead, MailboxUpdate
from app.services.google_mailbox_service import handle_google_callback
from app.services.mailbox_oauth_state import consume_mailbox_oauth_state, store_mailbox_oauth_state
from app.services.mailbox_service import (
    create_mailbox,
    get_user_mailboxes,
    get_mailbox_by_id,
    update_mailbox,
    delete_mailbox,
    update_user_email_sending_mode,
    get_mailboxes_by_domain,
    get_email_statistics,
)
from app.services.session_service import cookie_secure
from app.dependencies.auth import get_current_user
from app.core.google_gmail import GOOGLE_GMAIL_SCOPES, GOOGLE_OAUTH_CONFIG
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/mailboxes", tags=["Mailboxes"])



@router.post("/google/connect")
async def connect_google_mailbox(
    request: Request,
    current_user=Depends(get_current_user)
):
    campaign_id = request.query_params.get("campaign_id")
    csrf_token = secrets.token_urlsafe(32)

    try:
        await store_mailbox_oauth_state(
            state=csrf_token,
            user_id=str(current_user.id),
            campaign_id=campaign_id,
        )
    except Exception:
        logger.exception("Failed to store mailbox OAuth state")
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")

    params = {
        "client_id": GOOGLE_OAUTH_CONFIG["client_id"],
        "redirect_uri": GOOGLE_OAUTH_CONFIG["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(GOOGLE_GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": csrf_token,
    }

    url = f"{GOOGLE_OAUTH_CONFIG['auth_uri']}?{urlencode(params)}"
    response = JSONResponse(content={"auth_url": url})
    response.set_cookie(
        key="mailbox_oauth_state",
        value=csrf_token,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request.url.scheme == "https"),
        max_age=600,
        path="/",
    )
    return response



@router.get("/google/callback")
async def google_mailbox_callback(
    request: Request,
    db: AsyncSession = Depends(get_session),
):
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    
    # Check for missing parameters
    if not code:
        frontend_url = settings.FRONTEND_URL
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message=Missing authorization code"
        return RedirectResponse(url=redirect_url)
    
    if not state:
        frontend_url = settings.FRONTEND_URL
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message=Missing user state"
        return RedirectResponse(url=redirect_url)

    cookie_value = request.cookies.get("mailbox_oauth_state", "")
    if cookie_value != state:
        frontend_url = settings.FRONTEND_URL
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message=Invalid OAuth state"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response

    try:
        stored = await consume_mailbox_oauth_state(state)
    except Exception:
        logger.exception("Failed to consume mailbox OAuth state")
        frontend_url = settings.FRONTEND_URL
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message=Invalid OAuth state"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response

    if not stored:
        frontend_url = settings.FRONTEND_URL
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message=Invalid OAuth state"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response

    user_id = stored["user_id"]
    campaign_id = stored.get("campaign_id")

    try:
        await handle_google_callback(
            code=code,
            user_id=user_id,
            db=db,
        )
        
        # Get frontend URL and redirect based on whether we came from campaign flow
        frontend_url = settings.FRONTEND_URL
        if campaign_id:
            # Redirect to campaign-creation page if we came from campaign flow
            # Store campaign ID in sessionStorage by including it in URL - frontend will handle it
            redirect_url = f"{frontend_url}/dashboard/campaign-creation?gmail_connected=true&campaign_id={campaign_id}"
        else:
            # Otherwise redirect to email accounts page
            redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_connected=true"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response
    except HTTPException as e:
        logger.error("Google mailbox callback error: %s", e.detail)
        frontend_url = settings.FRONTEND_URL
        error_message = e.detail if e.detail else "Failed to connect Gmail account"
        encoded_message = quote(error_message)
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message={encoded_message}"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response
    except Exception:
        logger.exception("Unexpected error in Google mailbox callback")
        frontend_url = settings.FRONTEND_URL
        encoded_message = quote("An unexpected error occurred. Please try again.")
        redirect_url = f"{frontend_url}/dashboard/email-accounts?gmail_error=true&message={encoded_message}"
        response = RedirectResponse(url=redirect_url)
        response.delete_cookie("mailbox_oauth_state", path="/")
        return response

@router.post("/", response_model=MailboxRead)
async def create_mailbox_route(
    payload: MailboxCreate,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await create_mailbox(
        payload=payload,
        db=db,
        user_id=current_user.id,
    )


@router.get("/", response_model=list[MailboxRead])
async def list_my_mailboxes(
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await get_user_mailboxes(current_user.id, db)


@router.get("/statistics")
async def get_email_statistics_route(
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """Get email statistics: sent today, delivery rate, bounce rate."""
    return await get_email_statistics(current_user.id, db)


@router.get("/domain/{domain_id}", response_model=list[MailboxRead])
async def get_mailboxes_by_domain_route(
    domain_id: str,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """Get all mailboxes for a specific domain that belong to the current user."""
    return await get_mailboxes_by_domain(domain_id, current_user.id, db)


@router.put("/email-sending-mode")
async def set_email_sending_mode(
    payload: EmailSendingModeUpdate,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await update_user_email_sending_mode(
        user_id=current_user.id,
        mode=payload.email_sending_mode,
        db=db,
    )

@router.get("/{mailbox_id}", response_model=MailboxRead)
async def get_mailbox(
    mailbox_id: str,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await get_mailbox_by_id(mailbox_id, current_user.id, db)


@router.put("/{mailbox_id}", response_model=MailboxRead)
async def update_mailbox_route(
    mailbox_id: str,
    payload: MailboxUpdate,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await update_mailbox(
        mailbox_id,
        payload,
        current_user.id,
        db,
    )


@router.delete("/{mailbox_id}")
async def delete_mailbox_route(
    mailbox_id: str,
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    await delete_mailbox(mailbox_id, current_user.id, db)
    return {"status": "deleted"}


