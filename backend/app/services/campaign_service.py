import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, or_, delete
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi import HTTPException, status
from datetime import datetime, timezone
from uuid import UUID
from typing import Union
from app.models.campaign import Campaign, CampaignStatus
from app.schemas.campaign import CampaignCreate, CampaignUpdate, PaginatedCampaignResponse, CampaignResponse
from app.models.campaign_lead import CampaignLead
from app.models.lead import Lead
from app.models.campaign_goal import CampaignGoal
from app.models.campaign_category import CampaignCategory
from app.core.pagination import normalize_pagination, paginated_payload
from app.models.user import User
from app.enums.email_sending_mode import EmailSendingMode
from app.services.campaign_guard import ensure_campaign_editable
from app.services.campaign_sender_email import (
    resolve_campaign_sender_email,
    resolve_campaign_sender_emails_batch,
)
async def create_campaign(
    user_id: Union[UUID, str],
    payload: CampaignCreate,
    db: AsyncSession
):
    """Step 1: Create a draft campaign."""

    try:
        # Convert user_id to UUID if it's a string (user.id is already UUID, but handle both cases)
        if isinstance(user_id, str):
            try:
                user_id = UUID(user_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid user_id format: {user_id}"
                )

        # No restriction on duplicate campaign names - users can create campaigns with same name and description
        
        # Validate goal_id if provided (not None)
        # Goals can be user-specific (user_id matches) or global (user_id is NULL)
        if payload.goal_id is not None:
            logger.info(f"Validating goal_id: {payload.goal_id} for user {user_id}")
            try:
                goal = await db.scalar(
                    select(CampaignGoal).where(
                        CampaignGoal.id == payload.goal_id,
                        or_(CampaignGoal.user_id == user_id, CampaignGoal.user_id.is_(None))
                    )
                )
                if not goal:
                    logger.info(f"Goal not found: {payload.goal_id}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Campaign goal with ID '{payload.goal_id}' not found."
                    )
            except HTTPException:
                raise
            except SQLAlchemyError as e:
                logger.error(f"Error validating goal: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="A database error occurred. Please try again."
                )

        # Validate category_id if provided (not None)
        # Categories can be user-specific (user_id matches) or global (user_id is NULL)
        if payload.category_id is not None:
            logger.info(f"Validating category_id: {payload.category_id} for user {user_id}")
            try:
                category = await db.scalar(
                    select(CampaignCategory).where(
                        CampaignCategory.id == payload.category_id,
                        or_(CampaignCategory.user_id == user_id, CampaignCategory.user_id.is_(None))
                    )
                )
                if not category:
                    logger.info(f"Category not found: {payload.category_id}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Campaign category with ID '{payload.category_id}' not found."
                    )
            except HTTPException:
                raise
            except SQLAlchemyError as e:
                logger.error(f"Error validating category: {str(e)}")
                raise HTTPException(
                    status_code=500,
                    detail="A database error occurred. Please try again."
                )
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found."
            )

        campaign = Campaign(
            user_id=user_id,
            name=payload.name,
            description=payload.description,
            goal_id=payload.goal_id,
            category_id=payload.category_id,
            tags=",".join(payload.tags) if payload.tags else None,
            status=CampaignStatus.DRAFT,
            # SNAPSHOT email sending mode at creation time
            email_sending_mode=user.email_sending_mode,
        )

        db.add(campaign)

        # --- Safe commit with rollback ---
        try:
            await db.commit()
            await db.refresh(campaign)
        except IntegrityError:
            await db.rollback()
            logger.exception("IntegrityError while creating campaign for user %s", campaign.user_id)
            raise HTTPException(
                status_code=409,
                detail="A campaign with this name already exists. Please choose a different name."
            )
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("DB error while creating campaign for user %s", campaign.user_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to create campaign. Please try again."
            )

        return {
            "id": campaign.id,
            "name": campaign.name,
            "description": campaign.description,
            "goal_id": campaign.goal_id,
            "category_id": campaign.category_id,
            "tags": campaign.tags.split(",") if campaign.tags else [],
            "status": campaign.status.value if campaign.status else "draft",
            "lead_count": 0,
            "avg_lead_score": 0.0,
            "leads": [],
            "email_sending_mode": (
                campaign.email_sending_mode.value
                if campaign.email_sending_mode is not None
                else None
            ),
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
            "launched_at": getattr(campaign, "launched_at", None),
        }

    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again.",
        )


async def get_all_campaigns(
    user_id: Union[UUID, str],
    db: AsyncSession,
    search: str | None = None,
    min_avg_score: float | None = None,
    max_avg_score: float | None = None,
    page: int = 1,
    per_page: int = 50,
):
    """List all campaigns with stats + pagination metadata.
    OPTIMIZED: Uses subqueries to fetch all stats in 2 queries instead of N+2.
    """

    try:
        # Convert user_id to UUID if it's a string
        if isinstance(user_id, str):
            try:
                user_id = UUID(user_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid user_id format: {user_id}"
                )

        page, per_page, offset = normalize_pagination(page, per_page)

        # --- Create subqueries for stats (OPTIMIZATION: avoid N+1) ---
        # Subquery 1: Count leads per campaign
        lead_count_subquery = (
            select(
                CampaignLead.campaign_id,
                func.count(CampaignLead.id).label("lead_count_agg")
            )
            .group_by(CampaignLead.campaign_id)
            .correlate(Campaign)
            .subquery()
        )

        # Subquery 2: Average lead score per campaign
        avg_score_subquery = (
            select(
                CampaignLead.campaign_id,
                func.coalesce(
                    func.avg(func.coalesce(Lead.lead_score, CampaignLead.lead_score)),
                    0
                ).label("avg_score_agg")
            )
            .select_from(CampaignLead)
            .outerjoin(Lead, CampaignLead.lead_id == Lead.id)
            .group_by(CampaignLead.campaign_id)
            .correlate(Campaign)
            .subquery()
        )

        avg_score_expr = func.coalesce(avg_score_subquery.c.avg_score_agg, 0)

        # --- Total count for pagination (include avg-score filters in SQL) ---
        try:
            total_query = (
                select(func.count())
                .select_from(Campaign)
                .where(Campaign.user_id == user_id)
            )
            if search:
                total_query = total_query.where(Campaign.name.ilike(f"%{search}%"))
            if min_avg_score is not None or max_avg_score is not None:
                total_query = total_query.outerjoin(
                    avg_score_subquery, Campaign.id == avg_score_subquery.c.campaign_id
                )
                if min_avg_score is not None:
                    total_query = total_query.where(avg_score_expr >= min_avg_score)
                if max_avg_score is not None:
                    total_query = total_query.where(avg_score_expr <= max_avg_score)
            total_items = (await db.scalar(total_query)) or 0
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to load campaigns. Please try again."
            )

        # --- Fetch campaigns with stats joined in ONE query ---
        try:
            query = (
                select(
                    Campaign,
                    func.coalesce(lead_count_subquery.c.lead_count_agg, 0).label("lead_count"),
                    avg_score_expr.label("avg_score")
                )
                .where(Campaign.user_id == user_id)
                .outerjoin(lead_count_subquery, Campaign.id == lead_count_subquery.c.campaign_id)
                .outerjoin(avg_score_subquery, Campaign.id == avg_score_subquery.c.campaign_id)
            )
            if search:
                query = query.where(Campaign.name.ilike(f"%{search}%"))
            if min_avg_score is not None:
                query = query.where(avg_score_expr >= min_avg_score)
            if max_avg_score is not None:
                query = query.where(avg_score_expr <= max_avg_score)
            
            # Campaign.id is a unique tiebreaker so paginated ordering is stable across
            # page requests: without it, campaigns sharing a created_at could be repeated
            # on one page and dropped from another (see the leads-list fix in lead_service).
            query = query.order_by(Campaign.created_at.desc(), Campaign.id).limit(per_page).offset(offset)
            
            # Execute full query (with stats) - SINGLE query instead of N+2
            result = await db.execute(query)
            rows = result.all()
            
        except SQLAlchemyError as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to load campaigns. Please try again."
            )

        campaign_objs = [row[0] for row in rows]
        sender_by_campaign = await resolve_campaign_sender_emails_batch(
            db,
            user_id=user_id,
            campaigns=campaign_objs,
        )

        enriched = []

        for row in rows:
            campaign = row[0]
            lead_count = int(row[1]) if row[1] is not None else 0
            avg_score = round(float(row[2]), 2) if row[2] is not None else 0.0

            # Ensure status has a value - handle both enum and string cases
            if campaign.status is None:
                status_value = "draft"
            elif isinstance(campaign.status, CampaignStatus):
                status_value = campaign.status.value
            elif isinstance(campaign.status, str):
                status_value = campaign.status
            else:
                status_value = str(campaign.status)
            
            # Handle tags safely
            if campaign.tags is None:
                tags_list = []
            elif isinstance(campaign.tags, str):
                tags_list = campaign.tags.split(",") if campaign.tags.strip() else []
            elif isinstance(campaign.tags, list):
                tags_list = campaign.tags
            else:
                tags_list = []
            
            # Ensure all required fields are present and properly typed
            if campaign.created_at is None or campaign.updated_at is None:
                logger.warning(f"⚠️ Warning: Campaign {campaign.id} has None datetime fields")
                from datetime import datetime, timezone
                fallback_time = datetime.now(timezone.utc)
                created_at = campaign.created_at or fallback_time
                updated_at = campaign.updated_at or fallback_time
            else:
                created_at = campaign.created_at
                updated_at = campaign.updated_at
            
            # Get email_sending_mode value
            email_sending_mode_value = None
            if campaign.email_sending_mode is not None:
                if isinstance(campaign.email_sending_mode, EmailSendingMode):
                    email_sending_mode_value = campaign.email_sending_mode.value
                else:
                    email_sending_mode_value = str(campaign.email_sending_mode)
            
            campaign_data = {
                "id": campaign.id,
                "name": campaign.name or "",
                "description": campaign.description,
                "goal_id": campaign.goal_id,
                "category_id": campaign.category_id,
                "tags": tags_list,
                "status": status_value,
                "lead_count": lead_count,
                "avg_lead_score": avg_score,
                "leads": [],  # Empty list for list view (not needed here)
                "email_sending_mode": email_sending_mode_value,
                "sender_email": sender_by_campaign.get(str(campaign.id)),
                "created_at": created_at,
                "updated_at": updated_at,
                "launched_at": getattr(campaign, "launched_at", None),
            }
            enriched.append(campaign_data)

        return paginated_payload(
            enriched,
            total_items=total_items,
            page=page,
            per_page=per_page,
        )

    except HTTPException:
        # Re-raise HTTPExceptions as-is
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        logger.error(f"SQLAlchemy error in get_all_campaigns: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to load campaigns. Please try again."
        )
    except Exception as e:
        logger.error(f"Unexpected error in get_all_campaigns: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to load campaigns. Please try again."
        )


async def get_campaign_by_id(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Fetch single campaign with stats and linked leads."""

    # --- Safe fetch campaign ---
    try:
        campaign = await db.scalar(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    # --- Safe lead stats query (handles deleted leads using snapshot) ---
    try:
        # Count all campaign leads (including deleted ones)
        lead_count_query = select(func.count(CampaignLead.id)).where(CampaignLead.campaign_id == campaign.id)
        lead_count = (await db.scalar(lead_count_query)) or 0
        
        # Calculate average score using snapshot data or lead data
        if lead_count > 0:
            # Use COALESCE to prefer lead_score from Lead table, fallback to snapshot
            stats_query = (
                select(
                    func.coalesce(
                        func.avg(func.coalesce(Lead.lead_score, CampaignLead.lead_score)),
                        0
                    ).label("avg_lead_score")
                )
                .select_from(CampaignLead)
                .outerjoin(Lead, CampaignLead.lead_id == Lead.id)
                .where(CampaignLead.campaign_id == campaign.id)
            )
            result = await db.execute(stats_query)
            avg_score = round(float(result.scalar() or 0), 2)
        else:
            avg_score = 0.0
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    # --- Safe fetch linked leads (using snapshot if lead deleted) ---
    try:
        campaign_leads_query = (
            select(CampaignLead)
            .where(CampaignLead.campaign_id == campaign.id)
            .options(selectinload(CampaignLead.lead))
        )
        campaign_leads = (await db.scalars(campaign_leads_query)).all()
        
        # Build leads list from campaign_leads, using snapshot if lead is deleted
        leads_data = []
        for cl in campaign_leads:
            if cl.lead:
                # Lead still exists
                leads_data.append({
                    "id": cl.lead.id,
                    "business_name": cl.lead.business_name,
                    "industry": cl.lead.industry,
                    "email": cl.lead.email,
                    "lead_score": cl.lead.lead_score,
                })
            elif cl.business_name:
                # Lead deleted, use snapshot
                leads_data.append({
                    "id": cl.lead_id or cl.id,  # Use lead_id if available, otherwise campaign_lead.id
                    "business_name": cl.business_name,
                    "industry": cl.industry,
                    "email": cl.email,
                    "lead_score": cl.lead_score,
                })
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    # Get email_sending_mode value
    email_sending_mode_value = None
    if campaign.email_sending_mode is not None:
        if isinstance(campaign.email_sending_mode, EmailSendingMode):
            email_sending_mode_value = campaign.email_sending_mode.value
        else:
            email_sending_mode_value = str(campaign.email_sending_mode)

    sender_email = await resolve_campaign_sender_email(
        db,
        campaign_id=campaign.id,
        user_id=user_id,
        email_sending_mode=campaign.email_sending_mode,
    )
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "goal_id": campaign.goal_id,
        "category_id": campaign.category_id,
        "tags": campaign.tags.split(",") if campaign.tags else [],
        "status": campaign.status.value,
        "lead_count": lead_count or 0,
        "avg_lead_score": avg_score,
        "leads": leads_data,
        "email_sending_mode": email_sending_mode_value,
        "sender_email": sender_email,
        "email_subject": campaign.email_subject,
        "email_content": campaign.email_content,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "launched_at": getattr(campaign, "launched_at", None),
    }


async def update_campaign(
    campaign_id: str,
    user_id: str,
    payload: CampaignUpdate,
    db: AsyncSession
):
    """Edit a draft campaign before proceeding to next steps."""

    # --- Safe fetch campaign ---
    try:
        campaign = await db.scalar(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )

    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )

    ensure_campaign_editable(campaign, action="modify")

    # --- Apply updates if provided ---
    if payload.name is not None:
        campaign.name = payload.name
    if payload.description is not None:
        campaign.description = payload.description
    if payload.goal_id is not None:
        campaign.goal_id = payload.goal_id
    if payload.category_id is not None:
        campaign.category_id = payload.category_id
    if payload.tags is not None:
        campaign.tags = ",".join(payload.tags)
    if payload.email_sending_mode is not None:
        campaign.email_sending_mode = payload.email_sending_mode

    campaign.updated_at = datetime.now(timezone.utc)

    # --- Safe commit with rollback ---
    try:
        await db.commit()
        await db.refresh(campaign)
        return {
            "id": campaign.id,
            "name": campaign.name,
            "description": campaign.description,
            "goal_id": campaign.goal_id,
            "category_id": campaign.category_id,
            "tags": campaign.tags.split(",") if campaign.tags else [],
            "status": campaign.status.value if campaign.status else "draft",
            "lead_count": 0,
            "avg_lead_score": 0.0,
            "leads": [],
            "email_sending_mode": (
                campaign.email_sending_mode.value
                if campaign.email_sending_mode is not None
                else None
            ),
            "created_at": campaign.created_at,
            "updated_at": campaign.updated_at,
            "launched_at": getattr(campaign, "launched_at", None),
        }
    except SQLAlchemyError as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update campaign. Please try again."
        )


async def delete_campaign(
    campaign_id: str,
    user_id: str,
    db: AsyncSession
):
    """Delete a draft campaign. Only draft campaigns can be deleted."""
    
    # Convert user_id to UUID if it's a string
    if isinstance(user_id, str):
        try:
            user_id = UUID(user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid user_id format: {user_id}"
            )
    
    # Fetch campaign
    try:
        campaign = await db.scalar(
            select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail="A database error occurred. Please try again."
        )
    
    if not campaign:
        raise HTTPException(
            status_code=404,
            detail="Campaign not found or unauthorized."
        )
    
    ensure_campaign_editable(campaign, action="delete")
    
    # Delete the campaign (cascade will handle related records)
    try:
        await db.execute(delete(Campaign).where(Campaign.id == campaign_id))
        await db.commit()
        return {"message": "Campaign deleted successfully."}
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete campaign. Please try again."
        )


async def auto_set_email_sending_mode_for_draft_campaigns(
    user_id: str,
    email_sending_mode: EmailSendingMode,
    db: AsyncSession
):
    """Automatically set email_sending_mode for *unset* draft campaigns.

    IMPORTANT:
    - Users can choose SYSTEM vs USER per campaign in the campaign flow.
    - We should only auto-fill email_sending_mode when it is NULL (unset), and
      never overwrite an explicit per-campaign selection.
    """
    try:
        # Find all draft campaigns for this user that don't have email_sending_mode set
        result = await db.execute(
            select(Campaign).where(
                Campaign.user_id == user_id,
                Campaign.status == CampaignStatus.DRAFT,
                Campaign.email_sending_mode.is_(None),
            )
        )
        draft_campaigns = result.scalars().all()
        
        # Update all draft campaigns
        for campaign in draft_campaigns:
            campaign.email_sending_mode = email_sending_mode
            campaign.updated_at = datetime.now(timezone.utc)
        
        if draft_campaigns:
            await db.commit()
            return len(draft_campaigns)
        
        return 0
    except Exception as e:
        await db.rollback()
        # Don't raise error - this is a background operation
        logger.warning(f"Warning: Failed to auto-set email_sending_mode for draft campaigns: {str(e)}")
        return 0
