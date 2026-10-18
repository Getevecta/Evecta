import logging
from typing import List, Optional
from uuid import UUID

logger = logging.getLogger(__name__)
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from app.database.session import get_session
from app.models.user import User
from app.dependencies.auth import get_current_user
from app.services.lead_service import (
    promote_lead_log_to_database,
    get_all_leads,
    get_leads_by_ids,
    delete_lead,
    delete_leads_bulk,
    toggle_lead_star,
    create_lead_service,
    update_lead_service,
)
from app.services.lead_upload_service import (
    MAX_EXCEL_BYTES,
    assert_xlsx_upload,
    import_leads_from_excel,
)
from app.models.lead import Lead
from app.models.lead_log import LeadLog
from app.schemas.response import BaseResponse
from app.schemas.lead import LeadLogResponse, LeadLogListResponse, LeadResponse, LeadLogLeadResponse, PromoteLeadsRequest, BulkDeleteLeadsRequest, BulkGetLeadsRequest, LeadCreate, LeadUpdate, lead_to_response
from app.schemas.lead_chat import ChatCompleteRequest
from app.core.limiter import limiter

router = APIRouter(prefix="/leads", tags=["Leads"])


def _route_error(msg: str, detail: str) -> None:
    """Log and raise a 500 for unexpected errors in lead routes."""
    logger.exception(msg)
    raise HTTPException(status_code=500, detail=detail)


# --- Save / Cancel Chat Session ---
@router.post("/chat/complete", response_model=BaseResponse, status_code=status.HTTP_200_OK)
async def chat_complete(
    payload: ChatCompleteRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Handles post-chat actions:
    - action='save': Promote selected or all leads from Lead Log → Lead Database.
    - action='cancel': Do nothing (ignore session).
    """
    try:
        action = payload.action.lower()

        if action == "save":
            if not payload.log_id:
                raise HTTPException(status_code=400, detail="log_id is required to promote leads.")

            log = await db.scalar(select(LeadLog).where(LeadLog.id == payload.log_id, LeadLog.user_id == user.id))
            if not log:
                raise HTTPException(status_code=404, detail="Lead log not found or unauthorized access.")

            promote_result = await promote_lead_log_to_database(
                log_id=payload.log_id,
                db=db,
                user_id=user.id,
                selected_lead_ids=payload.selected_lead_ids,
            )

            return BaseResponse(
                status="success",
                message="Selected leads promoted successfully." if payload.selected_lead_ids else "All leads promoted successfully.",
                data=promote_result.data,
            )

        elif action == "cancel":
            return BaseResponse(
                status="success",
                message="Action cancelled — no leads were saved or changed.",
                data={"status": "cancelled"},
            )

        else:
            raise HTTPException(status_code=400, detail="Invalid action. Must be 'save' or 'cancel'.")

    except HTTPException:
        raise
    except SQLAlchemyError:
        await db.rollback()
        _route_error("DB error promoting leads for user %s" % user.id, "Database error while saving leads. Please try again.")
    except Exception:
        await db.rollback()
        _route_error("Unexpected error promoting leads for user %s" % user.id, "An unexpected error occurred. Please try again.")



# --- Get all lead logs (sessions) ---
@router.get("/leadlogs", response_model=List[LeadLogListResponse])
async def get_lead_logs(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List all individual chat sessions (not grouped) for the current user."""
    try:
        from app.models.lead_log_lead import LeadLogLead
        from sqlalchemy import func
        
        # Get all logs for the user, ordered by most recent first
        query = select(LeadLog).where(LeadLog.user_id == user.id).order_by(LeadLog.created_at.desc())
        result = await db.scalars(query)
        logs = result.all()
        
        if not logs:
            return []
        
        # Get lead counts for each log
        log_ids = [log.id for log in logs]
        lead_counts_query = (
            select(LeadLogLead.lead_log_id, func.count(LeadLogLead.id).label('count'))
            .where(LeadLogLead.lead_log_id.in_(log_ids))
            .group_by(LeadLogLead.lead_log_id)
        )
        lead_counts_result = await db.execute(lead_counts_query)
        lead_counts_dict = {row.lead_log_id: row.count for row in lead_counts_result.all()}
        
        # Create individual entries for each log (not grouped)
        result_list = []
        for log in logs:
            # Only include logs that have leads
            lead_count = lead_counts_dict.get(log.id, 0)
            if lead_count > 0:
                log_data = LeadLogListResponse.model_validate(log)
                log_data.lead_count = lead_count
                result_list.append(log_data)
        
        # Already sorted by created_at desc from the query
        return result_list
    except HTTPException:
        raise
    except Exception:
        _route_error("Error fetching lead logs for user %s" % user.id, "Failed to fetch lead logs. Please try again.")

 
# --- View leads inside a log session ---
@router.get("/leadlogs/{log_id}", response_model=LeadLogResponse)
async def view_lead_log(
    log_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch leads from the specific log session only (not grouped with other sessions)."""
    try:
        from app.models.lead_log_lead import LeadLogLead
        
        # Get the specific log
        log_query = select(LeadLog).where(LeadLog.id == log_id, LeadLog.user_id == user.id)
        log_result = await db.scalar(log_query)
        if not log_result:
            raise HTTPException(status_code=404, detail="Lead log not found.")
        
        logger.info(f"🔍 Found log: {log_id}, Query: '{log_result.query}'")
        
        # Get leads ONLY from this specific log (not from other logs with same query)
        leads_query = select(LeadLogLead).where(
            LeadLogLead.lead_log_id == log_id,
            )
        leads_result = await db.scalars(leads_query)
        leads = leads_result.all()
        
        logger.info(f"🔍 Found {len(leads)} leads for this specific log {log_id}")
        
        # Convert leads to response format
        lead_responses = []
        for idx, lead in enumerate(leads):
            try:
                lead_responses.append(LeadLogLeadResponse.model_validate(lead))
            except Exception as lead_error:
                logger.exception("Error converting lead %d/%d (ID: %s): %s", idx + 1, len(leads), lead.id, lead_error)
                continue
        
        logger.info(f" Successfully converted {len(lead_responses)}/{len(leads)} leads to response format")
        
        # Create response with leads from this specific log only
        response = LeadLogResponse(
            id=log_result.id,
            chat_title=log_result.chat_title,
            query=log_result.query,
            promoted=log_result.promoted,
            status=log_result.status,
            created_at=log_result.created_at,
            leads=lead_responses
        )
        
        logger.info(f"📤 Returning response with {len(response.leads)} leads for log {log_id}")
        
        return response
    except HTTPException:
        raise
    except Exception:
        _route_error("Error fetching lead log %s for user %s" % (log_id, user.id), "Failed to fetch lead log. Please try again.")

@router.get("/leadlogs/{log_id}/enrichment-status")
async def get_enrichment_status(
    log_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    from app.models.lead_log_lead import LeadLogLead
    from sqlalchemy import func
    from app.utils.chat_recovery import (
        ENRICHMENT_TIMEOUT_SECONDS,
        build_enrichment_timeout_recovery,
    )

    log = await db.scalar(
        select(LeadLog).where(
            LeadLog.id == log_id,
            LeadLog.user_id == user.id
        )
    )
    if not log:
        raise HTTPException(status_code=404, detail="Lead log not found")

    # Fetch enrichment data
    result = await db.execute(
        select(
            LeadLogLead.id,
            LeadLogLead.email,
            LeadLogLead.enrichment_status,
            LeadLogLead.lead_score,
        ).where(LeadLogLead.lead_log_id == log_id)
    )
    rows = result.all()

    # Build summary
    summary = {"processing": 0, "done": 0, "failed": 0}
    for r in rows:
        summary[r.enrichment_status] += 1

    return_payload = {
        "log_id": str(log_id),
        "summary": {
            **summary,
            "total": len(rows),
        },
        "leads": [
            {
                "id": str(r.id),
                "email": r.email,
                "enrichment_status": r.enrichment_status,
                "lead_score": r.lead_score,
            }
            for r in rows
        ],
    }
    created = log.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - created).total_seconds() if created else 0
    if summary["processing"] > 0 and elapsed >= ENRICHMENT_TIMEOUT_SECONDS:
        return_payload["recovery"] = build_enrichment_timeout_recovery()
        return_payload["recovery_kind"] = "enrichment_timeout"
    return return_payload

@router.post("/leadlogs/{log_id}/promote", response_model=BaseResponse)
async def promote_lead_log(
    log_id: UUID,
    body: PromoteLeadsRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Promote selected or all leads from a lead log into the main Lead Database.
    If selected_lead_ids not provided, promotes all leads.
    """
    return await promote_lead_log_to_database(
        log_id=log_id,
        db=db,
        user_id=user.id,
        selected_lead_ids=body.selected_lead_ids,
    )

# --- Upload leads from Excel ---
@router.post("/upload", response_model=BaseResponse, status_code=status.HTTP_200_OK)
async def upload_leads_from_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """
    Import leads from an Excel (.xlsx) file directly into the Lead Database.

    Required in the header row (aliases accepted, case-insensitive):
    - Company name — e.g. business_name, company, name
    - Email — e.g. email, email address

    Optional: industry, contact_number, address, website.

    Each data row must have non-empty company name and email. Duplicates are skipped automatically.
    Maximum 1 000 rows per upload. Maximum file size 5 MB. Only .xlsx (ZIP) files are accepted.
    """
    try:
        file_bytes = await file.read(MAX_EXCEL_BYTES + 1)
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read the uploaded file.")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    assert_xlsx_upload(file_bytes)

    return await import_leads_from_excel(
        file_bytes=file_bytes,
        filename=file.filename or "",
        user_id=user.id,
        db=db,
    )


# --- Create a new lead ---
@router.post("", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    lead_data: LeadCreate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        lead = await create_lead_service(
            db=db,
            lead_data=lead_data,
            user_id=user.id,
        )

        return BaseResponse(
            status="success",
            message="Lead created successfully.",
            data=lead_to_response(lead),
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=500,
            detail="Database error while creating lead",
        )


# --- Get all saved leads ---
@router.get("", response_model=BaseResponse)
async def get_leads(
    search: str | None = Query(None, description="Search term for company, email, etc."),
    min_score: int | None = Query(None),
    max_score: int | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Retrieve user leads from permanent Lead table with pagination."""
    try:
        return await get_all_leads(user.id, db, search, min_score, max_score, page, limit)
    except HTTPException:
        raise
    except Exception:
        _route_error("Error fetching leads for user %s" % user.id, "Failed to fetch leads. Please try again.")


@router.post("/bulk-get", response_model=BaseResponse, status_code=status.HTTP_200_OK)
@limiter.limit("60/minute")
async def bulk_get_leads_endpoint(
    request: Request,
    payload: BulkGetLeadsRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch many leads by ids in one request."""
    try:
        return await get_leads_by_ids(payload.lead_ids, user.id, db)
    except HTTPException:
        raise
    except Exception:
        _route_error("Error bulk-fetching leads", "Failed to fetch selected leads. Please try again.")


# --- Get a single lead ---
@router.get("/{lead_id}", response_model=BaseResponse)
async def get_lead_by_id(
    lead_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Fetch a specific lead from Lead table."""
    query = select(Lead).where(Lead.id == lead_id, Lead.user_id == user.id)
    lead = await db.scalar(query)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")
    return BaseResponse(message="Lead retrieved successfully.", data=lead_to_response(lead))


# --- Update a lead ---
@router.put("/{lead_id}", response_model=BaseResponse, status_code=status.HTTP_200_OK)
async def update_lead(
    lead_id: UUID,
    lead_data: LeadUpdate,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    try:
        lead = await update_lead_service(
            db=db,
            lead_id=lead_id,
            user_id=user.id,
            lead_data=lead_data,
        )

        return BaseResponse(
            status="success",
            message="Lead updated successfully.",
            data=lead_to_response(lead),
        )

    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while updating lead",
        )



# --- Toggle star status for a lead ---
@router.put("/{lead_id}/star", response_model=BaseResponse, status_code=status.HTTP_200_OK)
async def toggle_star_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Toggle the starred status of a lead."""
    try:
        return await toggle_lead_star(lead_id, user.id, db)
    except HTTPException:
        raise
    except Exception:
        _route_error("Error toggling star for lead %s" % lead_id, "Failed to update lead. Please try again.")


# --- Bulk delete leads ---
# NOTE: declared before the "/{lead_id}" route. It's POST + a static path so it
# wouldn't collide, but keeping it above the path-param routes avoids surprises.
@router.post("/bulk-delete", response_model=BaseResponse, status_code=status.HTTP_200_OK)
@limiter.limit("30/minute")
async def bulk_delete_leads_endpoint(
    request: Request,
    payload: BulkDeleteLeadsRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete up to 1000 of the user's leads in a single transaction.

    The 1000-id cap is enforced by BulkDeleteLeadsRequest (over-cap → 422).
    """
    try:
        return await delete_leads_bulk(payload.lead_ids, user.id, db)
    except HTTPException:
        raise
    except Exception:
        _route_error("Error bulk-deleting leads", "Failed to delete leads. Please try again.")


# --- Delete a lead ---
@router.delete("/{lead_id}", response_model=BaseResponse, status_code=status.HTTP_200_OK)
async def delete_lead_endpoint(
    lead_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete lead from permanent table."""
    try:
        return await delete_lead(lead_id, user.id, db)
    except HTTPException:
        raise
    except Exception:
        _route_error("Error deleting lead %s" % lead_id, "Failed to delete lead. Please try again.")

