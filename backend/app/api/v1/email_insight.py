from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.email_activity import EmailActivity, EmailStatus
from datetime import datetime, timezone

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.services.email_event_service import apply_email_event
from app.services.email_insight_service import get_system_email_insights, get_user_email_accounts_service, get_user_email_overview_service
from app.utils.open_classifier import OpenClassification, classify_open

router = APIRouter(prefix="/email-accounts", tags=["Email Insights"])


@router.get("/email/open")
async def track_open(
    request: Request,
    db: AsyncSession = Depends(get_session),
    t: str = None,
    campaign_id: str = None,
    lead_id: str = None,
):
    """Tracking pixel endpoint. Accepts opaque token (?t=) or legacy IDs for old emails."""

    user_agent = request.headers.get("user-agent", "")

    # Cheap pre-filter: known scanners / proxies / Apple MPP prefetch — no DB hit.
    if classify_open(user_agent) != OpenClassification.HUMAN:
        return {"message": "ok"}

    email_activity = None

    # New path: look up by secure token
    if t:
        result = await db.execute(
            select(EmailActivity).where(EmailActivity.tracking_token == t)
        )
        email_activity = result.scalars().first()

    # Legacy fallback: look up by raw IDs (for emails sent before this change).
    # A lead can have several sends in a campaign (follow-ups/retries) —
    # attribute the open to the most recent one.
    if email_activity is None and campaign_id and lead_id:
        result = await db.execute(
            select(EmailActivity)
            .where(
                EmailActivity.campaign_id == campaign_id,
                EmailActivity.lead_id == lead_id,
            )
            .order_by(EmailActivity.sent_at.desc())
        )
        email_activity = result.scalars().first()

    if not email_activity:
        # Return 200 silently — don't reveal whether the token/IDs are valid
        return {"message": "ok"}

    # Full classification with the timing guard: a pixel load seconds after
    # delivery (or send, when no delivery event exists for USER mailboxes)
    # is scanner/proxy prefetch, not a human open.
    now = datetime.now(timezone.utc)
    reference = email_activity.delivered_at or email_activity.sent_at
    classification = classify_open(
        user_agent,
        request.client.host if request.client else None,
        occurred_at=now,
        delivered_at=reference,
    )
    if classification != OpenClassification.HUMAN:
        return {"message": "ok"}

    apply_email_event(email_activity, "open", occurred_at=now)

    try:
        await db.commit()
    except Exception:
        await db.rollback()

    return {"message": "ok"}

@router.get("/system/insights")
async def system_email_insights(
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    """
    SYSTEM email pool insights for logged-in user.
    """
    return await get_system_email_insights(
        user_id=current_user.id,
        db=db,
    )



# USER EMAIL OVERVIEW (CARDS)
@router.get("/user/overview")
async def user_email_overview(
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await get_user_email_overview_service(
        user_id=current_user.id,
        db=db,
    )


# USER EMAIL ACCOUNTS TABLE
@router.get("/user/accounts")
async def user_email_accounts(
    db: AsyncSession = Depends(get_session),
    current_user=Depends(get_current_user),
):
    return await get_user_email_accounts_service(
        user_id=current_user.id,
        db=db,
    )