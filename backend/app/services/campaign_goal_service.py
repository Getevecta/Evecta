from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, or_, func
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException
from datetime import datetime, timezone

from app.core.pagination import normalize_pagination, paginated_payload
from app.models.campaign_goal import CampaignGoal
from app.schemas.campaign_goal import CampaignGoalCreate, CampaignGoalUpdate


# -----------------------------------------------------------------------------------
# CREATE GOAL
# -----------------------------------------------------------------------------------
async def create_campaign_goal(
    user_id: str, payload: CampaignGoalCreate, db: AsyncSession
):
    """
    Create a new goal for a user.
    Includes:
    - Duplicate name check
    - Safe DB execution
    """
    try:
        # Prevent duplicate goal names
        existing = await db.scalar(
            select(CampaignGoal)
            .where(CampaignGoal.user_id == user_id)
            .where(CampaignGoal.name == payload.name)
        )
        if existing:
            raise HTTPException(status_code=400, detail="Goal name already exists.")

        goal = CampaignGoal(
            name=payload.name,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db.add(goal)
        await db.commit()
        await db.refresh(goal)
        return goal

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")


# -----------------------------------------------------------------------------------
# LIST USER GOALS
# -----------------------------------------------------------------------------------
async def get_goals(user_id: str, db: AsyncSession, *, page: int = 1, per_page: int = 50):
    """Fetch a page of goals for a user (includes default goals)."""
    try:
        page, per_page, offset = normalize_pagination(page, per_page)
        filters = or_(
            CampaignGoal.user_id.is_(None),
            CampaignGoal.user_id == user_id,
        )
        total_items = int(
            await db.scalar(select(func.count()).select_from(CampaignGoal).where(filters)) or 0
        )
        result = await db.scalars(
            select(CampaignGoal)
            .where(filters)
            .order_by(CampaignGoal.created_at.desc(), CampaignGoal.id)
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
# UPDATE GOAL
# -----------------------------------------------------------------------------------
async def update_campaign_goal(
    goal_id: str, user_id: str, payload: CampaignGoalUpdate, db: AsyncSession
):
    """
    Update (rename) a goal.
    Handles:
    - Goal not found
    - Unauthorized access
    - Duplicate name prevention
    """
    try:
        goal = await db.get(CampaignGoal, goal_id)

        if not goal or goal.user_id != user_id:
            raise HTTPException(
                status_code=404,
                detail="Goal not found or unauthorized."
            )

        # Check if new name already exists
        duplicate = await db.scalar(
            select(CampaignGoal)
            .where(CampaignGoal.user_id == user_id)
            .where(CampaignGoal.name == payload.name)
            .where(CampaignGoal.id != goal_id)
        )
        if duplicate:
            raise HTTPException(
                status_code=400, detail="Another goal already has this name."
            )

        goal.name = payload.name
        goal.updated_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(goal)
        return goal

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")


# -----------------------------------------------------------------------------------
# DELETE GOAL
# -----------------------------------------------------------------------------------
async def delete_campaign_goal(
    goal_id: str, user_id: str, db: AsyncSession
):
    """
    Delete a goal safely.
    - Validates goal exists
    - Validates user access
    - Cascade-safe
    """
    try:
        query = delete(CampaignGoal).where(
            CampaignGoal.id == goal_id,
            CampaignGoal.user_id == user_id,
        )

        result = await db.execute(query)
        await db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Goal not found.")

        return {"message": "Goal deleted successfully."}

    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail="A database error occurred. Please try again.")
