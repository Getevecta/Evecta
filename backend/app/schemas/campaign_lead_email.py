from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.utils.header_safety import CONTENT_MAX_LENGTH, SUBJECT_MAX_LENGTH, require_safe_header, require_safe_text


class CampaignLeadEmailResponse(BaseModel):
    id: UUID
    campaign_id: UUID
    campaign_lead_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    lead_index: int
    business_name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    lead_score: Optional[int] = None
    context_score: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    generation_status: str
    compliance_status: str
    spam_score: Optional[int] = None
    risk_level: Optional[str] = None
    review_status: str
    regeneration_count: int
    variant_metadata: Optional[dict[str, Any]] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CampaignEmailGenerationStatusResponse(BaseModel):
    campaign_id: UUID
    total: int = 0
    complete: int = 0
    queued: int = 0
    generating: int = 0
    pending: int = 0
    ready: int = 0
    failed: int = 0
    compliance_passed: int = 0
    compliance_failed: int = 0
    is_complete: bool = False
    instant_generated: Optional[int] = None
    queued_background: Optional[bool] = None
    remaining: Optional[int] = None
    already_running: Optional[bool] = None


class CampaignEmailGenerateResponse(CampaignEmailGenerationStatusResponse):
    message: str = Field(default="Generation started")


class EmailReviewBatchRequest(BaseModel):
    email_ids: Optional[list[UUID]] = None
    approve_all: bool = False
    reject_all_pending: bool = False


class CampaignEmailReviewSummaryResponse(BaseModel):
    campaign_id: UUID
    has_per_lead_emails: bool = False
    total: int = 0
    pending_review: int = 0
    approved: int = 0
    rejected: int = 0
    generation_in_progress: int = 0
    generation_failed: int = 0
    ready_for_review: int = 0
    can_launch: bool = False
    launch_blockers: list[str] = Field(default_factory=list)
    updated: Optional[int] = None


class CampaignLeadEmailRegenerateResponse(BaseModel):
    email: CampaignLeadEmailResponse
    message: str = "Email regenerated"


class CampaignLeadEmailUpdateRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=SUBJECT_MAX_LENGTH)
    body: str = Field(..., min_length=1, max_length=CONTENT_MAX_LENGTH)
    mark_spam_passed: bool = False

    @field_validator("subject")
    @classmethod
    def subject_no_newlines(cls, v: str):
        return require_safe_header(v, name="subject", max_length=SUBJECT_MAX_LENGTH)

    @field_validator("body")
    @classmethod
    def body_is_safe(cls, v: str):
        return require_safe_text(
            v, name="body", max_length=CONTENT_MAX_LENGTH, allow_newlines=True, strip=False
        )


class CampaignLeadEmailUpdateResponse(BaseModel):
    email: CampaignLeadEmailResponse
    message: str = "Email updated"
