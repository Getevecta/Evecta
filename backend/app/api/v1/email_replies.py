from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.schemas.email_reply import EmailReplyCreate
from app.services.reply_sender_service import send_reply_email
from app.core.limiter import limiter


router = APIRouter(prefix="/emails", tags=["Email Replies"])


# Reply back to the lead inside the same email thread
@router.post("/reply")
@limiter.limit("30/hour")
async def reply_to_lead(
    request: Request,
    payload: EmailReplyCreate,
    db: AsyncSession = Depends(get_session),
    user = Depends(get_current_user)
):
    """
    Backend endpoint for replying to a lead inside Evecta.
    """
    try:
        reply_activity = await send_reply_email(
            activity_id=str(payload.activity_id),
            reply_text=payload.reply_text,
            user_id=user.id,
            db=db,
        )

        return {
            "status": "reply_sent",
            "reply_id": str(reply_activity.id),
            "lead_id": str(reply_activity.lead_id),
            "campaign_id": str(reply_activity.campaign_id),
            "reply_text": reply_activity.reply_text,
            "sent_at": reply_activity.sent_at
        }

    except HTTPException:
        raise

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")

    except Exception as e:
        raise HTTPException(status_code=400, detail="Something went wrong. Please try again.")
