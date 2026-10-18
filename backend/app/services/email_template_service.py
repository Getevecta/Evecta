import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func, text, update, not_

logger = logging.getLogger(__name__)
from sqlalchemy.exc import SQLAlchemyError, DataError
from fastapi import HTTPException, status
from datetime import datetime, timezone
from typing import Dict, List
from uuid import UUID
from uuid import uuid4

from app.models.email_template import EmailTemplate, TemplateCategory
from app.models.campaign import Campaign
from app.schemas.email_template import EmailTemplateCreate, EmailTemplateUpdate


def _as_uuid(value, label: str) -> UUID:
    try:
        return UUID(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"Invalid {label} format.")


def _category_from_row(value) -> TemplateCategory | None:
    valid_category_values = {cat.value for cat in TemplateCategory}
    if value and value in valid_category_values:
        try:
            return TemplateCategory(value)
        except ValueError:
            return None
    return None


def _template_from_row(row) -> EmailTemplate:
    return EmailTemplate(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        subject=row.subject,
        content=row.content,
        category=_category_from_row(row.category),
        is_favorite=bool(getattr(row, "is_favorite", False)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

# Default email templates to seed for each user
DEFAULT_TEMPLATES = [
    {
        "name": "Professional",
        "subject": "A quick idea for {{business_name}} (15 mins?)",
        "content": """Hello!

Greetings,

It has been good to see how {{business_name}} is moving in the {{industry}} space. The focus behind your initiatives and the speed of execution suggest a team that knows what it wants to achieve.

From what we've been building, we believe there may be a few specific areas where our strengths fit well with yours and could be useful for your upcoming initiatives. If you're open to it, we'd like to share those points briefly and see whether collaboration makes sense.

A focused 15-minute conversation should be enough to decide. We can adjust to a time that suits your schedule.

With warm regards,

[Your Name]""",
        "category": TemplateCategory.PROFESSIONAL
    },
   
    {
        "name": "Value Proportion",
        "subject": "Quick operational improvement idea for {{business_name}}",
        "content": """Hi {{business_name}} Team,

I came across {{business_name}} while looking into teams doing solid work in the {{industry}} space, and it felt worth reaching out.

We've been helping organizations in {{industry}} tighten a few everyday workflows—mainly reducing manual effort, speeding up turnaround time, and improving consistency. In a few recent cases, this led to:

lower operating overhead

faster processing in key steps

fewer routine errors

If you're open to it, I can share the exact approach in a quick 10-minute call and see whether it's relevant for {{business_name}} in {{location}}.

Best regards,

[Your Name]""",
        "category": TemplateCategory.VALUE_PROPOSITION
    },
   
    {
        "name": "Network Outreach",
        "subject": "Connecting with fellow {{ industry }} professionals",
        "content": """Hi {{business_name}} Team,

I've been following how teams in {{industry}} are adjusting to recent shifts, and {{business_name}} stood out.

I work with organizations in this {{industry}} space and would appreciate a short conversation to exchange notes on what's working and what's changing. If there's a fit, great—if not, no worries.

If you're open to it, I'm happy to do a quick call.

Best regards,

[Your Name]""",
        "category": TemplateCategory.NETWORK_OUTREACH
    }
]

# create
async def create_email_template(
    user_id: str,
    payload: EmailTemplateCreate,
    db: AsyncSession
):
    """Create a new email template."""

    try:
        # Prevent duplicate name for same user
        try:
            existing = await db.scalar(
                select(EmailTemplate).where(
                    EmailTemplate.user_id == user_id,
                    EmailTemplate.name == payload.name
                )
            )
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=500,
                detail="A database error occurred. Please try again."
            )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Template with name '{payload.name}' already exists."
            )

        template = EmailTemplate(
            user_id=user_id,
            name=payload.name,
            subject=payload.subject,
            content=payload.content,
            category=payload.category
        )

        db.add(template)

        # --- Safe commit with rollback ---
        try:
            await db.commit()
            await db.refresh(template)
        except SQLAlchemyError as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Failed to save changes. Please try again."
            )

        return template

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )


# SEED DEFAULT TEMPLATES
async def ensure_default_templates_exist(user_id: str, db: AsyncSession):
    """Ensure default templates exist for a user. Creates them if they don't exist, and updates existing ones with latest content."""
    try:
        # Get all existing templates for this user
        existing_templates_result = await db.execute(
            select(EmailTemplate).where(EmailTemplate.user_id == user_id)
        )
        existing_templates = {t.name: t for t in existing_templates_result.scalars().all()}
        
        # Create a map of default template names for quick lookup
        default_templates_map = {t["name"]: t for t in DEFAULT_TEMPLATES}
        
        now = datetime.now(timezone.utc)
        has_changes = False
        
        # Update existing default templates or create missing ones
        for template_data in DEFAULT_TEMPLATES:
            template_name = template_data["name"]
            
            if template_name in existing_templates:
                # Template exists - update it with latest content
                existing_template = existing_templates[template_name]
                # Only update if content has changed to avoid unnecessary updates
                if (existing_template.subject != template_data["subject"] or 
                    existing_template.content != template_data["content"] or
                    existing_template.category != template_data["category"]):
                    existing_template.subject = template_data["subject"]
                    existing_template.content = template_data["content"]
                    existing_template.category = template_data["category"]
                    existing_template.updated_at = now
                    has_changes = True
            else:
                # Template doesn't exist - create it
                template = EmailTemplate(
                    id=uuid4(),
                    user_id=user_id,
                    name=template_data["name"],
                    subject=template_data["subject"],
                    content=template_data["content"],
                    category=template_data["category"],
                    is_favorite=False,
                    created_at=now,
                    updated_at=now
                )
                db.add(template)
                has_changes = True
        
        # Commit only if there are changes
        if has_changes:
            await db.commit()
    except SQLAlchemyError as e:
        await db.rollback()
        # Don't raise exception here - just log and continue
        # This ensures the API still works even if seeding fails
        logger.warning(f"Warning: Failed to seed default templates for user {user_id}: {str(e)}")


# READ (List all templates)
async def get_all_email_templates(user_id: str, db: AsyncSession):
    """List all templates for current user. Automatically seeds default templates if none exist."""
    try:
        # Ensure default templates exist before fetching
        await ensure_default_templates_exist(user_id, db)
        user_uuid = _as_uuid(user_id, "user_id")

        # Raw SQL avoids SQLAlchemy enum validation issues on legacy category values.
        query = text("""
            SELECT id, user_id, name, subject, content, category::text as category, is_favorite, created_at, updated_at
            FROM email_templates
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """)
        result = await db.execute(query, {"user_id": user_uuid})
        return [_template_from_row(row) for row in result.fetchall()]
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Failed to load email templates. Please try again.")


# READ (Single)
async def get_email_template_by_id(template_id: str, user_id: str, db: AsyncSession):
    """Fetch one template."""
    try:
        template_uuid = _as_uuid(template_id, "template_id")
        user_uuid = _as_uuid(user_id, "user_id")

        query = text("""
            SELECT id, user_id, name, subject, content, category::text as category, is_favorite, created_at, updated_at
            FROM email_templates
            WHERE id = :template_id AND user_id = :user_id
        """)
        result = await db.execute(query, {"template_id": template_uuid, "user_id": user_uuid})
        row = result.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Template not found or unauthorized.")

        return _template_from_row(row)
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Failed to load email template. Please try again.")


# UPDATE
async def update_email_template(
    template_id: str,
    user_id: str,
    payload: EmailTemplateUpdate,
    db: AsyncSession
):
    """Update an existing template."""

    # --- Safe fetch template ---
    try:
        template = await db.get(EmailTemplate, template_id)
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    if not template or template.user_id != user_id:
        raise HTTPException(
            status_code=404,
            detail="Template not found or unauthorized."
        )

    # --- Apply updates ---
    if payload.name:
        template.name = payload.name
    if payload.subject:
        template.subject = payload.subject
    if payload.content:
        template.content = payload.content
    if payload.category is not None:
        template.category = payload.category
    if payload.is_favorite is not None:
        template.is_favorite = payload.is_favorite

    template.updated_at = datetime.now(timezone.utc)

    # --- Safe commit with rollback ---
    try:
        await db.commit()
        await db.refresh(template)
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    return template


async def toggle_email_template_favorite(template_id: str, user_id: str, db: AsyncSession):
    """Flip is_favorite in a single UPDATE ... RETURNING round trip."""
    template_uuid = _as_uuid(template_id, "template_id")
    user_uuid = _as_uuid(user_id, "user_id")
    now = datetime.now(timezone.utc)

    try:
        result = await db.execute(
            update(EmailTemplate)
            .where(
                EmailTemplate.id == template_uuid,
                EmailTemplate.user_id == user_uuid,
            )
            .values(
                is_favorite=not_(EmailTemplate.is_favorite),
                updated_at=now,
            )
            .returning(
                EmailTemplate.id,
                EmailTemplate.user_id,
                EmailTemplate.name,
                EmailTemplate.subject,
                EmailTemplate.content,
                EmailTemplate.category,
                EmailTemplate.is_favorite,
                EmailTemplate.created_at,
                EmailTemplate.updated_at,
            )
        )
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found or unauthorized.")
        await db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again.",
        )

    category = row.category
    if isinstance(category, str):
        category = _category_from_row(category)

    return EmailTemplate(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        subject=row.subject,
        content=row.content,
        category=category,
        is_favorite=bool(row.is_favorite),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# DELETE
async def delete_email_template(
    template_id: str,
    user_id: str,
    db: AsyncSession
):
    """Delete a specific template."""

    try:
        query = delete(EmailTemplate).where(
            EmailTemplate.id == template_id,
            EmailTemplate.user_id == user_id
        )
        result = await db.execute(query)

        # --- Safe commit with rollback ---
        try:
            await db.commit()
        except SQLAlchemyError as e:
            await db.rollback()
            raise HTTPException(
                status_code=500,
                detail="Failed to save changes. Please try again."
            )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Template not found or unauthorized."
            )

        return {"message": "Template deleted successfully."}

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )


# GET USAGE STATS
async def get_email_template_usage_stats(user_id: str, db: AsyncSession) -> Dict[str, int]:
    """Get usage count for each template (number of campaigns using each template)."""
    try:
        # Count campaigns grouped by template_id for the current user
        result = await db.execute(
            select(
                Campaign.template_id,
                func.count(Campaign.id).label("usage_count")
            )
            .where(
                Campaign.user_id == user_id,
                Campaign.template_id.isnot(None)
            )
            .group_by(Campaign.template_id)
        )
        
        # Convert to dictionary with template_id as string key
        usage_stats = {}
        for row in result.all():
            if row.template_id:
                usage_stats[str(row.template_id)] = row.usage_count
        
        return usage_stats
    except SQLAlchemyError as e:
        raise HTTPException(
            status_code=500,
            detail="Failed to load template stats. Please try again."
        )
