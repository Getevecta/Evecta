from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from app.models.email_activity import EmailActivity
from app.models.lead import Lead
from app.models.campaign import Campaign
from app.schemas.inbox import InboxItem
from app.utils.email_personalization import replace_placeholders


async def get_user_inbox(user_id: str, db: AsyncSession, campaign_filter: str = None, page: int = 1, per_page: int = 50):
    """
    Returns a unified inbox: list of ALL sent emails,
    sorted by most recent activity (reply or sent time).
    
    This fetches all sent emails - those with replies appear first,
    followed by emails without replies, all sorted by most recent activity.
    """
    try:
        # Base query - fetches ALL sent emails (both with and without replies)
        stmt = (
            select(EmailActivity, Lead, Campaign)
            .join(Lead, Lead.id == EmailActivity.lead_id)
            .join(Campaign, Campaign.id == EmailActivity.campaign_id)
            .where(
                Campaign.user_id == user_id,
            )
        )

        # Optional campaign filter
        if campaign_filter:
            stmt = stmt.where(Campaign.id == campaign_filter)

        # Sort by: replied emails first (by latest reply), then by sent time for non-replied
        stmt = stmt.order_by(
            desc(EmailActivity.replied),
            desc(EmailActivity.replied_at.isnot(None)),
            desc(EmailActivity.replied_at),
            desc(EmailActivity.sent_at)
        )

        per_page = min(per_page, 100)  # hard cap at 100
        offset = (page - 1) * per_page
        stmt = stmt.limit(per_page).offset(offset)

        rows = await db.execute(stmt)
        results = rows.all()

        inbox_items = []

        for activity, lead, campaign in results:
            # Replace placeholders in email content with actual lead data
            personalized_email = replace_placeholders(campaign.email_content, lead) if campaign.email_content else None
            
            inbox_items.append(
                InboxItem(
                    lead_id=str(lead.id),
                    lead_email=lead.email,
                    lead_name=lead.business_name,
                    lead_address=lead.address,
                    lead_contact=lead.contact_number,
                    lead_industry=lead.industry,
                    lead_score = lead.lead_score,

                    sent_email=personalized_email,
                    last_reply=activity.reply_text,
                    last_reply_time=activity.replied_at,

                    last_sent_time=activity.sent_at,
                    last_message_id=activity.message_id,
                    activity_id=str(activity.id),

                    campaign_id=str(campaign.id),
                    campaign_name=campaign.name,
                    starred=activity.starred if hasattr(activity, 'starred') else False,
                )
            )

        return inbox_items

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")

    except Exception as e:
        raise HTTPException(status_code=500, detail="Something went wrong. Please try again.")