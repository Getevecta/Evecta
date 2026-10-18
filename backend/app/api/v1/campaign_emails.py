import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limiter import limiter
from app.core.pagination import DEFAULT_PER_PAGE, PageQuery, PerPageQuery, paginated_payload
from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.campaign_lead import CampaignLead
from app.models.campaign_lead_email import CampaignLeadEmail
from app.models.user import User
from app.schemas.campaign_lead_email import (
    CampaignEmailGenerateResponse,
    CampaignEmailGenerationStatusResponse,
    CampaignEmailReviewSummaryResponse,
    CampaignLeadEmailRegenerateResponse,
    CampaignLeadEmailResponse,
    CampaignLeadEmailUpdateRequest,
    CampaignLeadEmailUpdateResponse,
    EmailReviewBatchRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.personalization_service import lead_data_from_sources, score_lead_context
from app.services.campaign_email_generation_service import (
    cancel_campaign_email_generation,
    discard_campaign_lead_emails,
    get_campaign_email_generation_status,
    list_campaign_lead_emails,
    resume_campaign_email_generation,
    start_campaign_email_generation,
)
from app.services.campaign_email_review_service import (
    approve_emails,
    get_email_review_summary,
    regenerate_email,
    reject_emails,
    update_lead_email,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/campaigns/{campaign_id}/emails", tags=["Campaign Lead Emails"])


def _review_summary_response(
    campaign_id: UUID,
    result: dict,
) -> CampaignEmailReviewSummaryResponse:
    """Build review summary response; service dict may already include campaign_id."""
    payload = {k: v for k, v in result.items() if k != "campaign_id"}
    return CampaignEmailReviewSummaryResponse(campaign_id=campaign_id, **payload)


def _serialize_row(row: CampaignLeadEmail) -> CampaignLeadEmailResponse:
    variant_meta = None
    if row.variant_metadata:
        try:
            variant_meta = json.loads(row.variant_metadata)
        except json.JSONDecodeError:
            variant_meta = None

    cl: CampaignLead | None = row.campaign_lead
    business_name = None
    email = None
    location = None
    lead_score = None
    context_score = None
    if cl:
        business_name = cl.business_name
        email = cl.email
        location = cl.address
        lead_score = cl.lead_score
        context_score = score_lead_context(lead_data_from_sources(campaign_lead=cl))
    elif row.lead:
        business_name = row.lead.business_name
        email = row.lead.email
        location = row.lead.address
        lead_score = row.lead.lead_score

    return CampaignLeadEmailResponse(
        id=row.id,
        campaign_id=row.campaign_id,
        campaign_lead_id=row.campaign_lead_id,
        lead_id=row.lead_id,
        lead_index=row.lead_index,
        business_name=business_name,
        email=email,
        location=location,
        lead_score=lead_score,
        context_score=context_score,
        subject=row.subject,
        body=row.body,
        generation_status=row.generation_status.value,
        compliance_status=row.compliance_status.value,
        spam_score=row.spam_score,
        risk_level=row.risk_level,
        review_status=row.review_status.value,
        regeneration_count=row.regeneration_count,
        variant_metadata=variant_meta,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/generate", response_model=CampaignEmailGenerateResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/hour")
async def generate_campaign_lead_emails(
    request: Request,
    campaign_id: UUID,
    regenerate_all: bool = Query(False, description="Regenerate every lead email, not only new/pending ones"),
    regenerate_failed: bool = Query(False, description="Regenerate only failed lead emails; leave ready ones untouched"),
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 4 — queue per-lead email generation in the background (poll /status)."""
    result = await start_campaign_email_generation(
        str(campaign_id),
        str(user.id),
        db,
        regenerate_all=regenerate_all,
        regenerate_failed=regenerate_failed,
    )
    already = result.get("already_running")
    return CampaignEmailGenerateResponse(
        campaign_id=campaign_id,
        total=result.get("total", 0),
        complete=result.get("complete", 0),
        queued=result.get("queued", 0),
        generating=result.get("generating", 0),
        pending=result.get("pending", 0),
        ready=result.get("ready", 0),
        failed=result.get("failed", 0),
        compliance_passed=result.get("compliance_passed", 0),
        compliance_failed=result.get("compliance_failed", 0),
        is_complete=result.get("is_complete", False),
        instant_generated=result.get("instant_generated"),
        queued_background=result.get("queued_background"),
        remaining=result.get("remaining"),
        already_running=already,
        message=(
            "Generation already in progress"
            if already
            else "Per-lead email generation started"
        ),
    )


@router.get("/status", response_model=CampaignEmailGenerationStatusResponse, status_code=status.HTTP_200_OK)
async def get_campaign_lead_emails_status(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Poll generation progress for a campaign."""
    result = await get_campaign_email_generation_status(str(campaign_id), str(user.id), db)
    return CampaignEmailGenerationStatusResponse(
        campaign_id=campaign_id,
        total=result.get("total", 0),
        complete=result.get("complete", 0),
        queued=result.get("queued", 0),
        generating=result.get("generating", 0),
        pending=result.get("pending", 0),
        ready=result.get("ready", 0),
        failed=result.get("failed", 0),
        compliance_passed=result.get("compliance_passed", 0),
        compliance_failed=result.get("compliance_failed", 0),
        is_complete=result.get("is_complete", False),
    )


@router.post("/cancel", response_model=CampaignEmailGenerateResponse, status_code=status.HTTP_200_OK)
async def cancel_campaign_lead_emails(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Stop remaining generation; proceed with emails already generated."""
    result = await cancel_campaign_email_generation(str(campaign_id), str(user.id), db)
    return CampaignEmailGenerateResponse(
        campaign_id=campaign_id,
        total=result.get("total", 0),
        complete=result.get("complete", 0),
        queued=result.get("queued", 0),
        generating=result.get("generating", 0),
        pending=result.get("pending", 0),
        ready=result.get("ready", 0),
        failed=result.get("failed", 0),
        compliance_passed=result.get("compliance_passed", 0),
        compliance_failed=result.get("compliance_failed", 0),
        is_complete=result.get("ready", 0) > 0,
        message=result.get("message", "Generation cancelled"),
    )


@router.post("/discard", response_model=CampaignEmailGenerateResponse, status_code=status.HTTP_200_OK)
async def discard_campaign_lead_emails_route(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Discard all per-lead emails so the user can return to compose and regenerate."""
    result = await discard_campaign_lead_emails(str(campaign_id), str(user.id), db)
    return CampaignEmailGenerateResponse(
        campaign_id=campaign_id,
        total=result.get("total", 0),
        complete=result.get("complete", 0),
        queued=result.get("queued", 0),
        generating=result.get("generating", 0),
        pending=result.get("pending", 0),
        ready=result.get("ready", 0),
        failed=result.get("failed", 0),
        compliance_passed=result.get("compliance_passed", 0),
        compliance_failed=result.get("compliance_failed", 0),
        is_complete=False,
        message="Per-lead emails discarded",
    )


@router.post("/resume", response_model=CampaignEmailGenerateResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/hour")
async def resume_campaign_lead_emails(
    request: Request,
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Resume stuck per-lead generation (queued but not processing)."""
    result = await resume_campaign_email_generation(str(campaign_id), str(user.id), db)
    return CampaignEmailGenerateResponse(
        campaign_id=campaign_id,
        total=result.get("total", 0),
        complete=result.get("complete", 0),
        queued=result.get("queued", 0),
        generating=result.get("generating", 0),
        pending=result.get("pending", 0),
        ready=result.get("ready", 0),
        failed=result.get("failed", 0),
        compliance_passed=result.get("compliance_passed", 0),
        compliance_failed=result.get("compliance_failed", 0),
        is_complete=result.get("is_complete", False),
        message="Generation resumed" if result.get("resumed") else "Generation already in progress or complete",
    )


@router.get("", response_model=PaginatedResponse[CampaignLeadEmailResponse], status_code=status.HTTP_200_OK)
async def get_campaign_lead_emails(
    campaign_id: UUID,
    page: PageQuery = 1,
    per_page: PerPageQuery = DEFAULT_PER_PAGE,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List per-lead generated emails for preview/review (paginated)."""
    rows, total_items, page, per_page = await list_campaign_lead_emails(
        str(campaign_id), str(user.id), db, page=page, per_page=per_page
    )
    return paginated_payload(
        [_serialize_row(row) for row in rows],
        total_items=total_items,
        page=page,
        per_page=per_page,
    )


@router.get("/review", response_model=CampaignEmailReviewSummaryResponse, status_code=status.HTTP_200_OK)
async def get_campaign_email_review_summary(
    campaign_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Step 5 — review summary and launch readiness."""
    result = await get_email_review_summary(str(campaign_id), str(user.id), db)
    return CampaignEmailReviewSummaryResponse(
        campaign_id=campaign_id,
        has_per_lead_emails=result.get("has_per_lead_emails", False),
        total=result.get("total", 0),
        pending_review=result.get("pending_review", 0),
        approved=result.get("approved", 0),
        rejected=result.get("rejected", 0),
        generation_in_progress=result.get("generation_in_progress", 0),
        generation_failed=result.get("generation_failed", 0),
        ready_for_review=result.get("ready_for_review", 0),
        can_launch=result.get("can_launch", False),
        launch_blockers=result.get("launch_blockers", []),
    )


@router.post("/review/approve", response_model=CampaignEmailReviewSummaryResponse, status_code=status.HTTP_200_OK)
async def approve_campaign_emails(
    campaign_id: UUID,
    payload: EmailReviewBatchRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Approve one, many, or all ready per-lead emails."""
    email_ids = [str(eid) for eid in payload.email_ids] if payload.email_ids else None
    result = await approve_emails(
        str(campaign_id),
        str(user.id),
        db,
        email_ids=email_ids,
        approve_all=payload.approve_all,
    )
    return _review_summary_response(campaign_id, result)


@router.post("/review/reject", response_model=CampaignEmailReviewSummaryResponse, status_code=status.HTTP_200_OK)
async def reject_campaign_emails(
    campaign_id: UUID,
    payload: EmailReviewBatchRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Reject one, many, or all pending per-lead emails."""
    email_ids = [str(eid) for eid in payload.email_ids] if payload.email_ids else None
    result = await reject_emails(
        str(campaign_id),
        str(user.id),
        db,
        email_ids=email_ids,
        reject_all_pending=payload.reject_all_pending,
    )
    return _review_summary_response(campaign_id, result)


@router.patch(
    "/{email_id}",
    response_model=CampaignLeadEmailUpdateResponse,
    status_code=status.HTTP_200_OK,
)
async def update_campaign_lead_email(
    campaign_id: UUID,
    email_id: UUID,
    payload: CampaignLeadEmailUpdateRequest,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Update a per-lead email draft (resets compliance until spam re-test passes)."""
    row = await update_lead_email(
        str(campaign_id),
        str(email_id),
        str(user.id),
        db,
        subject=payload.subject,
        body=payload.body,
        mark_spam_passed=payload.mark_spam_passed,
    )
    return CampaignLeadEmailUpdateResponse(
        email=_serialize_row(row),
        message="Spam check passed" if payload.mark_spam_passed else "Email updated",
    )


@router.post(
    "/{email_id}/regenerate",
    response_model=CampaignLeadEmailRegenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def regenerate_campaign_lead_email(
    campaign_id: UUID,
    email_id: UUID,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Regenerate a single per-lead email (resets review to pending)."""
    row, restored = await regenerate_email(str(campaign_id), str(email_id), str(user.id), db)
    return CampaignLeadEmailRegenerateResponse(
        email=_serialize_row(row),
        message=(
            "Could not generate a better draft — kept the previous version."
            if restored
            else "Email regenerated"
        ),
    )
