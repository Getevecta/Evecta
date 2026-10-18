import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from app.models.campaign import Campaign
from app.models.lead import Lead
from app.models.campaign_lead import CampaignLead
from app.models.email_activity import EmailActivity, EmailStatus
from app.models.user import User
from app.utils.email_sender import send_test_email
from app.utils.unsubscribe_url import build_unsubscribe_urls
from app.utils.email_unsubscribe_html import build_top_unsubscribe_html
from app.core.config import get_settings
from app.services.company_service import get_company_by_user_id
from app.utils.sender_name_extractor import (
    extract_company_name_from_content,
    extract_sender_name_from_content,
)
from app.utils.email_personalization import (
    build_footer,
    format_plain_text_as_html,
    replace_placeholders,
)


async def send_test_email_service(
    campaign_id: str,
    user_id: str,
    user_email: str,
    db: AsyncSession
):
    """
    Send a test email preview to the user's email address.
    Uses the first lead's data for personalization preview.
    """
    # Fetch campaign and verify ownership
    # Convert campaign_id and user_id to UUIDs for database query
    import uuid as uuid_lib
    campaign_uuid = uuid_lib.UUID(campaign_id) if isinstance(campaign_id, str) else campaign_id
    user_uuid = uuid_lib.UUID(user_id) if isinstance(user_id, str) else user_id
    
    campaign = await db.get(Campaign, campaign_uuid)
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )
    
    # Compare UUIDs properly
    if campaign.user_id != user_uuid:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    # Extract campaign data immediately to avoid lazy loading issues
    campaign_id_str = str(campaign.id)
    campaign_email_subject = campaign.email_subject
    campaign_email_content = campaign.email_content
    
    # Ensure draft is ready
    if not campaign_email_subject or not campaign_email_content:
        raise HTTPException(
            status_code=400,
            detail="Draft not ready. Please complete the email draft first."
        )

    # Fetch first lead for personalization preview (if available, using snapshot if deleted)
    campaign_lead_result = await db.scalars(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_uuid)
        .options(selectinload(CampaignLead.lead))
        .limit(1)
    )
    first_campaign_lead = campaign_lead_result.first()
    first_lead = None
    if first_campaign_lead:
        if first_campaign_lead.lead:
            # Lead still exists
            first_lead = first_campaign_lead.lead
        elif first_campaign_lead.business_name:
            # Lead deleted, create a mock lead from snapshot
            class SnapshotLead:
                def __init__(self, cl):
                    self.id = cl.lead_id or cl.id
                    self.business_name = cl.business_name or "Unknown"
                    self.email = cl.email
                    self.industry = cl.industry
                    self.address = cl.address
                    self.contact_number = cl.contact_number
                    self.website = cl.website
                    self.lead_score = cl.lead_score or 0
            first_lead = SnapshotLead(first_campaign_lead)
    
    # Extract first_lead attributes immediately to avoid lazy loading
    first_lead_id = str(first_lead.id) if first_lead else None
    first_lead_email = first_lead.email if first_lead else None
    first_lead_dict = {}
    if first_lead:
        # Extract all attributes immediately to avoid lazy loading
        for attr, value in first_lead.__dict__.items():
            if not attr.startswith("_") and value is not None:
                first_lead_dict[attr] = value

    # Personalize subject and content (use extracted dict to avoid lazy loading)
    test_subject = replace_placeholders(campaign_email_subject, first_lead_dict if first_lead else None)
    test_content_raw = replace_placeholders(campaign_email_content, first_lead_dict if first_lead else None)
    
    # Format email content to preserve line breaks
    test_content = format_plain_text_as_html(test_content_raw)

    # Generate unsubscribe URL for test email
    # For test emails, we need to find or create a lead with the user's email so unsubscribe works
    settings = get_settings()
    
    # Try to find a lead with the user's email address
    result = await db.scalars(
        select(Lead)
        .where(Lead.email == user_email)
        .where(Lead.user_id == user_uuid)
        .limit(1)
    )
    test_lead = result.first()
    
    if test_lead:
        test_email = user_email
        test_lead_id = str(test_lead.id)
    elif first_lead and first_lead_email == user_email:
        test_email = user_email
        test_lead_id = first_lead_id
    else:
        # No lead with user's email - create a temporary one for test email unsubscribe to work
        import uuid as uuid_lib
        # datetime and timezone are already imported at module level
        test_lead = Lead(
            id=uuid_lib.uuid4(),
            business_name="Test Email Recipient",
            email=user_email,
            user_id=user_uuid,
            email_subscribed=True,  # Start as subscribed
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(test_lead)
        await db.commit()
        await db.refresh(test_lead)

        # Extract test_lead.id immediately after refresh to avoid any session issues
        test_lead_id_extracted = str(test_lead.id)

        test_email = user_email
        test_lead_id = test_lead_id_extracted

    unsub_urls = build_unsubscribe_urls(test_lead_id, test_email)
    one_click_unsubscribe_url = unsub_urls["one_click_url"]
    confirm_unsubscribe_url = unsub_urls["confirm_url"]
    preferences_url = confirm_unsubscribe_url

    # Get sender name (priority: company name from email → database company name → sender name from email → user full name → default)
    # Extract from raw content (before HTML formatting) for better accuracy
    sender_name = "Evecta Outreach"
    try:
        user = await db.get(User, user_uuid)
        if user:
            # First, try to extract company name from email content (where [YourCompanyName] was written)
            email_company_name = extract_company_name_from_content(test_content_raw)
            if email_company_name:
                sender_name = email_company_name
            else:
                # Fall back to database company name
                try:
                    company = await get_company_by_user_id(db, str(user_uuid))
                    if company and company.company_name:
                        sender_name = company.company_name
                    else:
                        # Try to extract sender name from email content (after placeholder replacement, before HTML formatting)
                        email_sender_name = extract_sender_name_from_content(test_content_raw)
                        if email_sender_name:
                            sender_name = email_sender_name
                        elif user.full_name:
                            sender_name = user.full_name
                except Exception:
                    # If company fetch fails, try email content sender name, then user full name
                    email_sender_name = extract_sender_name_from_content(test_content_raw)
                    if email_sender_name:
                        sender_name = email_sender_name
                    elif user.full_name:
                        sender_name = user.full_name
        else:
            # If user not found, try to extract from email content
            email_company_name = extract_company_name_from_content(test_content_raw)
            if email_company_name:
                sender_name = email_company_name
            else:
                email_sender_name = extract_sender_name_from_content(test_content_raw)
                if email_sender_name:
                    sender_name = email_sender_name
    except Exception:
        # If user fetch fails, try to extract from email content
        email_company_name = extract_company_name_from_content(test_content_raw)
        if email_company_name:
            sender_name = email_company_name
        else:
            email_sender_name = extract_sender_name_from_content(test_content_raw)
            if email_sender_name:
                sender_name = email_sender_name

    # --- Evecta footer with unsubscribe controls (visible in test + real sends) ---
    test_content = test_content + build_footer(
        confirm_unsubscribe_url,
        sender_name=sender_name,
        preferences_url=preferences_url,
    )

    # Add test email banner
    test_banner = """
    <div style="background-color: #fff3cd; border: 2px solid #ffc107; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
        <h3 style="color: #856404; margin: 0 0 10px 0;">📧 TEST EMAIL PREVIEW</h3>
        <p style="color: #856404; margin: 0;">
            This is a test email preview of your campaign. The actual campaign emails will be sent to your leads when you launch the campaign.
        </p>
    </div>
    """
    test_content = (
        test_banner
        + build_top_unsubscribe_html(confirm_unsubscribe_url)
        + test_content
    )

    # Send test email to user
    try:
        result = await send_test_email(
            to_email=user_email,
            subject=f"[TEST] {test_subject}",
            html_content=test_content,
            campaign_id=campaign_id_str,  # Use pre-extracted string
            user_id=str(user_uuid),  # Convert to string
            db=db,
            unsubscribe_url=one_click_unsubscribe_url,
            lead_id=test_lead_id,  # Pass the lead_id so tracking token uses real lead_id
            sending_mode=campaign.email_sending_mode,
            display_sender=sender_name,
        )
        
        # Create EmailActivity record for test email so replies can be detected
        try:
            # Convert IDs to UUIDs if needed (use the already-converted user_uuid from above)
            import uuid as uuid_lib
            lead_uuid = uuid_lib.UUID(test_lead_id) if isinstance(test_lead_id, str) else test_lead_id
            # user_uuid is already defined above, don't redefine it
            
            email_activity = EmailActivity(
                campaign_id=campaign_uuid,  # Use UUID directly, not campaign.id to avoid lazy loading
                lead_id=lead_uuid,
                user_id=user_uuid,
                email=user_email,
                status=EmailStatus.SENT,
                sent_at=datetime.now(timezone.utc),
                sent_from=result.get("sent_from", "unknown"),
                replied=False,  # Will be set to True when reply is detected
            )
            db.add(email_activity)
            await db.commit()
            await db.refresh(email_activity)
            logger.info(f"[TEST EMAIL] ✅ Created EmailActivity record:")
            logger.info(f"   - Activity ID: {email_activity.id}")
            logger.info(f"   - Campaign ID: {campaign.id}")
            logger.info(f"   - Lead ID: {lead_uuid}")
            logger.info(f"   - User ID: {user_uuid}")
            logger.info(f"   - Sent From: {result.get('sent_from', 'unknown')}")
            logger.info(f"   - Email: {user_email}")
            logger.info(f"[TEST EMAIL] Replies to this test email will be detected!")
        except Exception as db_error:
            await db.rollback()
            logger.error(f"[WARNING] ❌ Failed to create EmailActivity for test email: {db_error}")
            import traceback
            traceback.print_exc()
            # Don't fail the whole operation if EmailActivity creation fails
        
        return {
            "campaign_id": str(campaign.id),
            "status": "sent",
            "message": f"Test email sent successfully to {user_email}",
            "test_email": user_email,
            "preview_subject": test_subject,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to send test email. Please try again."
        )

