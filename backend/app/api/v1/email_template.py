from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID
from pydantic import BaseModel

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.models.email_template import TemplateCategory
from app.schemas.email_template import (
    EmailTemplateCreate,
    EmailTemplateUpdate,
    EmailTemplateResponse
)
from app.services.email_template_service import (
    create_email_template,
    get_all_email_templates,
    get_email_template_by_id,
    update_email_template,
    delete_email_template,
    get_email_template_usage_stats,
    toggle_email_template_favorite,
)
from app.core.limiter import limiter

router = APIRouter(prefix="/email-templates", tags=["Email Templates"])


# -----------------------------------------------------
# CREATE
# -----------------------------------------------------
@router.post("", response_model=EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("15/minute")
async def create_template(
    request: Request,
    payload: EmailTemplateCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Create a new email template."""
    return await create_email_template(str(user.id), payload, db)


# -----------------------------------------------------
# READ (ALL)
# -----------------------------------------------------
@router.get("", response_model=List[EmailTemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """List all email templates for the current user."""
    return await get_all_email_templates(str(user.id), db)


# -----------------------------------------------------
# USAGE STATS (must be before /{template_id} route)
# -----------------------------------------------------
@router.get("/usage-stats")
@limiter.limit("20/minute")
async def get_template_usage_stats(
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Get usage statistics for all templates (count of campaigns using each template)."""
    return await get_email_template_usage_stats(str(user.id), db)


# -----------------------------------------------------
# CATEGORIES (must be before /{template_id} route)
# -----------------------------------------------------
class CategoryInfo(BaseModel):
    value: str
    label: str

@router.get("/categories", response_model=List[CategoryInfo])
async def get_template_categories(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Get all available email template categories."""
    category_labels = {
        "professional": "Professional",
        "value-proposition": "Value Proposition",
        "network-outreach": "Network Outreach",
        
    }
    return [
        CategoryInfo(value=category.value, label=category_labels.get(category.value, category.value.replace('-', ' ').title()))
        for category in TemplateCategory
    ]


# -----------------------------------------------------
# READ (SINGLE)
# -----------------------------------------------------
@router.get("/{template_id}", response_model=EmailTemplateResponse)
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Fetch one email template by ID."""
    return await get_email_template_by_id(str(template_id), user.id, db)


# -----------------------------------------------------
# UPDATE
# -----------------------------------------------------

@router.put("/{template_id}", response_model=EmailTemplateResponse)
async def update_template(
    template_id: UUID,
    payload: EmailTemplateUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Update an existing email template."""
    return await update_email_template(str(template_id), user.id, payload, db)


# -----------------------------------------------------
# TOGGLE FAVORITE
# -----------------------------------------------------
@router.patch("/{template_id}/toggle-favorite", response_model=EmailTemplateResponse)
async def toggle_template_favorite(
    template_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Toggle the favorite status of an email template."""
    return await toggle_email_template_favorite(str(template_id), user.id, db)


# -----------------------------------------------------
# DELETE
# -----------------------------------------------------
@router.delete("/{template_id}", status_code=status.HTTP_200_OK)
@limiter.limit("30/hour")
async def delete_template(
    request: Request,
    template_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user)
):
    """Delete an email template."""
    return await delete_email_template(str(template_id), user.id, db)
