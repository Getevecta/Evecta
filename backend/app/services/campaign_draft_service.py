from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException
from datetime import datetime, timezone
import re
import logging
import asyncio
import html as html_module
from app.models.campaign import Campaign, DraftType
from app.models.email_template import EmailTemplate
from app.models.lead import Lead
from app.models.campaign_lead import CampaignLead
from app.schemas.campaign_draft import CampaignDraftBase, AIDraftRequest
from app.core.personalization import normalize_tone
from app.core.email_tones import validate_tone_for_plan
from app.services.campaign_guard import ensure_campaign_editable
from app.services.personalization_service import (
    lead_data_from_sources,
    resolve_personalization,
)
from app.services.writing_spec_service import build_writing_spec_from_campaign_lead, writing_spec_summary
from app.utils.ai_email_generator import generate_campaign_ai_draft, get_fallback_template
from app.utils.spam_checker import check_email_spam


def _ensure_paragraph_breaks(plain_text: str) -> str:
    """
    If content has no or very few newlines (e.g. single paragraph from AI or manual),
    insert line breaks after sentence boundaries so send path shows paragraphs and
    sender extraction works. Used for AI and manual draft saves.
    """
    if not plain_text or plain_text.count("\n") >= 2:
        return plain_text
    # Same logic as mail_job.format_plain_text_as_html: break after ". " + capital letter
    return re.sub(r"\.\s+([A-Z])", r".\n\n\1", plain_text)


def strip_p_tags_from_content(content: str) -> str:
    """
    Remove all <p> tags from content before saving to database, preserving
    paragraph breaks as newlines so stored content keeps the structure.
    """
    if not content:
        return content

    # Normalize line endings so \r\n / \r don't break parsing or send path (template, AI, manual)
    content = content.replace("\r\n", "\n").replace("\r", "\n")

    # First, unescape any HTML entities (in case content was double-escaped)
    try:
        unescaped = html_module.unescape(content)
    except Exception:
        unescaped = content

    # Preserve line breaks from <br> tags (so content saved with <br> keeps structure)
    unescaped = re.sub(r'<br\s*/?>', '\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'<br>', '\n', unescaped, flags=re.IGNORECASE)

    # Preserve paragraph breaks: turn </p><p> into newlines before removing tags
    unescaped = re.sub(r'</p>\s*<p[^>]*>', '\n\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'</P>\s*<P[^>]*>', '\n\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'</p>', '\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'</P>', '\n', unescaped, flags=re.IGNORECASE)

    # Remove opening <p> tags (with or without attributes, case-insensitive)
    unescaped = re.sub(r'<p[^>]*>', '', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'<P[^>]*>', '', unescaped, flags=re.IGNORECASE)

    # Remove escaped HTML entities for <p> tags (and preserve breaks)
    unescaped = re.sub(r'&lt;/p&gt;\s*&lt;p[^&]*&gt;', '\n\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'&lt;/p&gt;', '\n', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'&lt;p[^&]*&gt;', '', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'&lt;P[^&]*&gt;', '', unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r'&lt;/P&gt;', '\n', unescaped, flags=re.IGNORECASE)

    # Normalize multiple newlines and trim
    unescaped = re.sub(r'\n\s*\n+', '\n\n', unescaped)
    return unescaped.strip()


def normalize_draft_content_for_storage(cleaned_content: str | None, ensure_breaks: bool = False) -> str | None:
    """
    Optional: ensure single-paragraph content gets sentence-boundary breaks so
    send path (format_plain_text_as_html + sender extraction) works for AI/manual too.
    """
    if not cleaned_content:
        return cleaned_content
    if ensure_breaks:
        cleaned_content = _ensure_paragraph_breaks(cleaned_content)
    return cleaned_content


# -----------------------------------------------------
# Get campaign draft
# -----------------------------------------------------
async def get_campaign_draft(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Retrieve draft data for a campaign."""

    # Fetch campaign and verify ownership
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    # Return draft data if available
    # Convert draft_type enum name to uppercase string (e.g., "TEMPLATE", "AI", "MANUAL")
    draft_type_str = None
    if campaign.draft_type:
        if hasattr(campaign.draft_type, "name"):
            draft_type_str = campaign.draft_type.name  # Returns "TEMPLATE", "AI", or "MANUAL"
        else:
            draft_type_str = str(campaign.draft_type).upper()
    
    return {
        "campaign_id": campaign.id,
        "draft_type": draft_type_str,
        "template_id": campaign.template_id,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "tone": campaign.tone,
        "description": campaign.description,
        "ai_email_prompt": campaign.ai_email_prompt,
    }


# -----------------------------------------------------
# Template draft
# -----------------------------------------------------
async def update_campaign_draft_template(
    campaign_id: str,
    user_id: str,
    payload: CampaignDraftBase,
    db: AsyncSession
):
    """Link selected email template to a campaign and copy its subject/content."""

    # Fetch campaign and check ownership
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    ensure_campaign_editable(campaign, action="edit")

    # Normalize incoming draft_type (enum or string)
    draft_type_value = (
        payload.draft_type.value.lower()
        if hasattr(payload.draft_type, "value")
        else str(payload.draft_type).lower()
    )

    # Only 'template' allowed for this step
    if draft_type_value != "template":
        raise HTTPException(
            status_code=400,
            detail="draft_type must be 'template' for this step."
        )

    # Template ID must be provided
    if not payload.template_id:
        raise HTTPException(
            status_code=400,
            detail="template_id is required for template selection."
        )

    # Fetch template and verify ownership
    template = await db.get(EmailTemplate, payload.template_id)
    if not template or template.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Template not found or unauthorized."
        )

    # Apply template to campaign
    # Use provided edited content if available, otherwise use template's default content
    # Remove <p> tags from content before saving to database
    raw_content = payload.email_content if payload.email_content else template.content
    cleaned_content = strip_p_tags_from_content(raw_content) if raw_content else None
    
    campaign.draft_type = DraftType.TEMPLATE
    campaign.template_id = template.id
    campaign.email_subject = payload.email_subject if payload.email_subject else template.subject
    campaign.email_content = cleaned_content
    campaign.updated_at = datetime.now(timezone.utc)

    # ---- SAFE COMMIT WITH ROLLBACK ----
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()  # ALWAYS rollback on commit failure
        raise HTTPException(
            status_code=500,
            detail="Failed to save changes. Please try again."
        )

    # Refresh only after successful commit
    await db.refresh(campaign)

    return {
        "campaign_id": campaign.id,
        "draft_type": getattr(campaign.draft_type, "name", campaign.draft_type),
        "template_id": campaign.template_id,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "tone": campaign.tone,
    }


# -----------------------------------------------------
# Manual draft
# -----------------------------------------------------
async def update_campaign_draft_manual(
    campaign_id: str,
    user_id: str,
    payload: CampaignDraftBase,
    db: AsyncSession
):
    """Save editable draft subject/content into a draft campaign.

    Notes:
    - The frontend can edit AI-generated drafts after generation. Those edits should
      not downgrade the draft_type to MANUAL; we allow draft_type = AI here too.
    - TEMPLATE drafts are still handled by update_campaign_draft_template since they
      require template_id validation.
    """

    # Fetch campaign and ensure ownership
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    ensure_campaign_editable(campaign, action="edit")

    # Normalize draft_type (handles enum or string)
    draft_type_value = (
        payload.draft_type.value.lower()
        if hasattr(payload.draft_type, "value")
        else str(payload.draft_type).lower()
    )

    if draft_type_value not in {DraftType.MANUAL.value.lower(), DraftType.AI.value.lower()}:
        raise HTTPException(
            status_code=400,
            detail="draft_type must be 'manual' or 'ai' for this step."
        )

    # Check manual subject/content provided
    if not payload.email_subject or not payload.email_content:
        raise HTTPException(
            status_code=400,
            detail="Both subject and content are required for manual draft."
        )

    # Apply manual email content: strip HTML to newlines, then ensure paragraph breaks if single line
    cleaned_content = strip_p_tags_from_content(payload.email_content) if payload.email_content else None
    cleaned_content = normalize_draft_content_for_storage(cleaned_content, ensure_breaks=True)
    
    campaign.draft_type = DraftType.AI if draft_type_value == DraftType.AI.value.lower() else DraftType.MANUAL
    campaign.template_id = None
    campaign.email_subject = payload.email_subject
    campaign.email_content = cleaned_content
    if payload.ai_email_prompt is not None and payload.ai_email_prompt.strip():
        campaign.ai_email_prompt = payload.ai_email_prompt.strip()
    campaign.updated_at = datetime.now(timezone.utc)

    # ---- SAFE COMMIT WITH ROLLBACK ----
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save changes. Please try again."
        )

    await db.refresh(campaign)

    return {
        "campaign_id": campaign.id,
        "draft_type": getattr(campaign.draft_type, "name", campaign.draft_type),
        "template_id": campaign.template_id,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "tone": campaign.tone,
        "ai_email_prompt": campaign.ai_email_prompt,
    }



# -----------------------------------------------------
# AI draft generation
# -----------------------------------------------------
async def generate_campaign_draft_ai(
    campaign_id: str,
    user_id: str,
    payload: AIDraftRequest,
    db: AsyncSession
):
    """Generate AI email subject & content for a campaign."""

    # Fetch campaign and verify ownership
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or campaign.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    ensure_campaign_editable(campaign, action="edit")

    from app.models.user import User
    user = await db.get(User, user_id)

    # Fetch sample leads for AI context from THIS campaign specifically
    result = await db.scalars(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_id)
        .options(selectinload(CampaignLead.lead))
        .limit(3)
    )
    campaign_leads = result.all()

    try:
        normalized_tone = validate_tone_for_plan(user.plan if user else "free", payload.tone)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    lead_samples = []
    for cl in campaign_leads:
        lead_data = lead_data_from_sources(campaign_lead=cl, lead=cl.lead)
        profile = resolve_personalization(
            plan=user.plan if user else "free",
            tone=normalized_tone,
            lead_data=lead_data,
        )
        sample = {
            "business_name": cl.business_name or lead_data.get("business_name"),
            "industry": cl.industry or lead_data.get("industry"),
            "effective_depth": profile["effective_depth"],
            "context": profile["context"],
        }
        lead_samples.append(sample)

    # Fetch user profile data
    user_profile = None
    if user:
        user_profile = {
            'full_name': user.full_name,
            'username': user.username,
            'email': user.email,
            'bio': user.bio,
            'department': user.department,
            'location': user.location,
            'website': user.website,
        }
    
    # Fetch company profile data if available
    company_profile = None
    try:
        from app.services.company_service import get_company_by_user_id
        company = await get_company_by_user_id(db, user_id)
        if company:
            company_profile = {
                'company_name': company.company_name,
                'company_description': company.company_description,
                'products_and_services': company.products_and_services,
            }
    except Exception:
        # Company profile not found or error - continue without it
        pass

    writing_spec = None
    if campaign_leads:
        writing_spec = build_writing_spec_from_campaign_lead(
            campaign_leads[0],
            plan=user.plan if user else "free",
            tone=normalized_tone,
            campaign_seed=str(campaign_id),
            index=0,
            user_profile=user_profile,
            company_profile=company_profile,
        )

    # Generate subject + content using AI
    # Inbox-safety gate on the primary LLM draft. The score-only judge is an LLM (noisy); using ~58+
    # avoids false rejects while still blocking obvious junk. Fallback template is always returned if
    # the primary draft misses the bar (see below).
    OUTREACH_READY_MIN_SCORE = 58  # inbox safety % (100 - spam_score)
    # One primary draft + spam. Retrying full generation multiplies latency (each round ≈ 1–2 LLM calls);
    # if the first draft misses Outreach Ready, we use the deterministic fallback template instead of 2–3 more full generations.
    max_spam_retries = 1
    subject = None
    content = None
    final_spam_score = None
    last_error = None
    
    # Helper function to strip HTML for spam checking
    def strip_html_for_check(html_text: str) -> str:
        """Strip HTML tags for spam checking."""
        text = re.sub(r'<[^>]+>', '', html_text)
        text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        return text.strip()
    
    # Try to generate AI email that passes the inbox-safety gate
    for spam_attempt in range(max_spam_retries):
        try:
            # Generate AI email (this function now has its own retry logic with timeout)
            generated_subject, generated_content = await generate_campaign_ai_draft(
                campaign_name="",  # Not used in prompt anymore
                tone=normalized_tone,
                description=payload.description,
                goal=None,  # Not used in prompt anymore
                category=None,  # Not used in prompt anymore
                leads_sample=lead_samples,
                user_profile=user_profile,
                company_profile=company_profile,
                writing_spec=writing_spec,
                user_id=user_id,
            )
            
            # Validate that the generated email is Outreach Ready
            plain_subject = strip_html_for_check(generated_subject)
            plain_content = strip_html_for_check(generated_content)
            
            # Score only: one small LLM response (no full rewrites) — see check_email_spam(..., score_only=True)
            spam_result = await check_email_spam(
                subject=plain_subject,
                body=plain_content,
                user_profile=user_profile,
                company_profile=company_profile,
                fast_mode=True,
                score_only=True,
                user_id=user_id,
            )
            
            spam_score = spam_result.get('spam_score', 100)
            inbox_safety_score = 100 - spam_score
            
            # Only accept primary draft if it passes the inbox-safety gate
            if inbox_safety_score >= OUTREACH_READY_MIN_SCORE:
                subject = generated_subject
                content = generated_content
                final_spam_score = spam_score
                break
            else:
                # Do NOT use this draft; retry or fall back later
                if spam_attempt < max_spam_retries - 1:
                    logging.info(
                        f"AI email not Outreach Ready (inbox safety {inbox_safety_score}%, need >= {OUTREACH_READY_MIN_SCORE}), "
                        f"retrying ({spam_attempt + 1}/{max_spam_retries})..."
                    )
                    continue
                else:
                    # Exhausted retries: do not use this content; subject/content stay None
                    logging.warning(
                        f"AI email did not meet Outreach Ready after {max_spam_retries} attempts (last inbox safety: {inbox_safety_score}%)"
                    )
                    break
                    
        except Exception as e:
            last_error = str(e)
            logging.warning(f"AI generation attempt {spam_attempt + 1} failed: {str(e)}")
            if spam_attempt < max_spam_retries - 1:
                await asyncio.sleep(0.2 * (spam_attempt + 1))
                continue
            else:
                break
    
    # If we have no Outreach Ready AI draft, try fallback template and ensure it passes spam check
    if subject is None or content is None:
        logging.warning(
            f"No Outreach Ready AI draft after {max_spam_retries} attempts. Trying fallback template. Last error: {last_error or 'spam score too high'}"
        )
        try:
            fallback_subject, fallback_content = get_fallback_template(
                description=payload.description,
                user_profile=user_profile,
                company_profile=company_profile
            )
            plain_fallback_subject = strip_html_for_check(fallback_subject)
            plain_fallback_content = strip_html_for_check(fallback_content)
            spam_result = await check_email_spam(
                subject=plain_fallback_subject,
                body=plain_fallback_content,
                user_profile=user_profile,
                company_profile=company_profile,
                fast_mode=True,
                score_only=True,
                user_id=user_id,
            )
            fallback_spam_score = spam_result.get('spam_score', 100)
            fallback_inbox_safety = 100 - fallback_spam_score
            subject = fallback_subject
            content = fallback_content
            final_spam_score = fallback_spam_score
            if fallback_inbox_safety >= OUTREACH_READY_MIN_SCORE:
                logging.info("Using fallback template; score-only check passed gate.")
            else:
                logging.warning(
                    "Using fallback template anyway (score-only inbox safety %s%% < %s%%); template is static B2B copy.",
                    fallback_inbox_safety,
                    OUTREACH_READY_MIN_SCORE,
                )
        except HTTPException:
            raise
        except Exception as fallback_error:
            logging.exception("AI draft generation fallback failed: %s", fallback_error)
            raise HTTPException(
                status_code=500,
                detail="AI draft generation failed. Please try again.",
            )

    # Save AI-generated content: strip <p> to newlines, then ensure paragraph breaks if single line (same as template)
    cleaned_content = strip_p_tags_from_content(content) if content else None
    cleaned_content = normalize_draft_content_for_storage(cleaned_content, ensure_breaks=True)
    
    campaign.draft_type = DraftType.AI
    campaign.template_id = None
    campaign.email_subject = subject
    campaign.email_content = cleaned_content
    campaign.tone = normalized_tone
    if payload.description and payload.description.strip():
        campaign.ai_email_prompt = payload.description.strip()
    campaign.updated_at = datetime.now(timezone.utc)

    # ---- SAFE COMMIT WITH ROLLBACK ----
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save changes. Please try again."
        )

    await db.refresh(campaign)

    subj_saved = (campaign.email_subject or "").strip()
    body_saved = (campaign.email_content or "").strip()
    if not subj_saved or not body_saved:
        logging.error(
            "AI draft commit produced empty fields (subject=%r, content_len=%s)",
            campaign.email_subject,
            len(campaign.email_content or ""),
        )
        raise HTTPException(
            status_code=500,
            detail="AI draft was saved with empty subject or body. Please try generating again.",
        )

    return {
        "campaign_id": campaign.id,
        "draft_type": (
            campaign.draft_type.name
            if hasattr(campaign.draft_type, "name")
            else str(campaign.draft_type)
        ),
        "template_id": campaign.template_id,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "tone": campaign.tone,
        "ai_email_prompt": campaign.ai_email_prompt,
    }
