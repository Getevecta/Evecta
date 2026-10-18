from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, func
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from datetime import datetime, timezone

from app.core.pagination import normalize_pagination, paginated_payload
from app.models.campaign_category import CampaignCategory
from app.schemas.campaign_category import CampaignCategoryCreate, CampaignCategoryUpdate


# -----------------------------------------------------------------------------------
# CREATE CATEGORY
# -----------------------------------------------------------------------------------
async def create_campaign_category(
    user_id: str, payload: CampaignCategoryCreate, db: AsyncSession
):
    """
    Create a new campaign category.
    Handles:
    - Duplicate names
    - DB exceptions
    """
    try:
        # Check for duplicate category name for same user
        existing = await db.scalar(
            select(CampaignCategory)
            .where(CampaignCategory.user_id == user_id)
            .where(CampaignCategory.name == payload.name)
        )
        if existing:
            raise HTTPException(status_code=400, detail="Category name already exists.")

        category = CampaignCategory(
            name=payload.name,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db.add(category)
        await db.commit()
        await db.refresh(category)
        return category

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")


# -----------------------------------------------------------------------------------
# FETCH ALL CATEGORIES
# -----------------------------------------------------------------------------------
async def get_categories(user_id: str, db: AsyncSession, *, page: int = 1, per_page: int = 50):
    """Return a page of categories for a user (includes default categories)."""
    try:
        page, per_page, offset = normalize_pagination(page, per_page)
        filters = or_(
            CampaignCategory.user_id.is_(None),
            CampaignCategory.user_id == user_id,
        )
        total_items = int(
            await db.scalar(select(func.count()).select_from(CampaignCategory).where(filters)) or 0
        )
        result = await db.scalars(
            select(CampaignCategory)
            .where(filters)
            .order_by(CampaignCategory.created_at.desc(), CampaignCategory.id)
            .offset(offset)
            .limit(per_page)
        )
        return paginated_payload(
            list(result.all()),
            total_items=total_items,
            page=page,
            per_page=per_page,
        )
    except SQLAlchemyError:
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")


# -----------------------------------------------------------------------------------
# UPDATE CATEGORY
# -----------------------------------------------------------------------------------
async def update_campaign_category(
    category_id: str, user_id: str, payload: CampaignCategoryUpdate, db: AsyncSession
):
    """
    Update category name.
    Handles:
    - Category not found
    - Unauthorized access
    - Duplicate name check
    """
    try:
        category = await db.get(CampaignCategory, category_id)

        if not category or category.user_id != user_id:
            raise HTTPException(
                status_code=404, detail="Category not found or unauthorized."
            )

        # Prevent duplicate category names
        duplicate = await db.scalar(
            select(CampaignCategory)
            .where(CampaignCategory.user_id == user_id)
            .where(CampaignCategory.name == payload.name)
            .where(CampaignCategory.id != category_id)
        )
        if duplicate:
            raise HTTPException(
                status_code=400, detail="Another category already exists with this name."
            )

        category.name = payload.name
        category.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(category)
        return category

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")


# -----------------------------------------------------------------------------------
# DELETE CATEGORY
# -----------------------------------------------------------------------------------
async def delete_campaign_category(
    category_id: str, user_id: str, db: AsyncSession
):
    """
    Delete a category.
    Handles:
    - Category not found
    - Unauthorized delete
    """
    try:
        query = delete(CampaignCategory).where(
            CampaignCategory.id == category_id,
            CampaignCategory.user_id == user_id
        )

        result = await db.execute(query)
        await db.commit()

        # If nothing deleted → no category found
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Category not found.")

        return {"message": "Category deleted successfully."}

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
