from typing import Any, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


class LaunchReadinessCheck(BaseModel):
    key: str
    label: str
    passed: bool
    message: str


class CampaignLaunchReadinessResponse(BaseModel):
    campaign_id: UUID
    campaign_status: str
    can_launch: bool
    launch_blockers: list[str] = Field(default_factory=list)
    checks: list[LaunchReadinessCheck] = Field(default_factory=list)
    approved_to_send: int = 0
    skipped_rejected: int = 0
    email_sending_mode: Optional[str] = None
    generation: Optional[dict[str, Any]] = None
    review: Optional[dict[str, Any]] = None


class CampaignLaunchResponse(BaseModel):
    campaign_id: UUID
    status: str
    queued: int
    approved: int
    skipped_rejected: int = 0
    message: str


class CampaignSendStatusResponse(BaseModel):
    campaign_id: UUID
    campaign_status: str
    total_jobs: int = 0
    queued: int = 0
    sending: int = 0
    sent: int = 0
    failed: int = 0
    in_progress: int = 0
    is_complete: bool = False
    progress_percent: int = 0


class CampaignLaunchSummary(BaseModel):
    """Campaign fields needed by launch/review screens, without hydrating leads."""
    id: UUID
    name: str
    description: Optional[str] = None
    goal_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    tags: Optional[list[str]] = None
    status: str
    lead_count: int = 0
    avg_lead_score: float = 0
    email_sending_mode: Optional[str] = None
    sender_email: Optional[str] = None
    email_subject: Optional[str] = None
    email_content: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    launched_at: Optional[datetime] = None


class CampaignLaunchViewResponse(BaseModel):
    campaign: CampaignLaunchSummary
    readiness: Optional[CampaignLaunchReadinessResponse] = None
    status: Optional[CampaignSendStatusResponse] = None
