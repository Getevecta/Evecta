from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List
from uuid import UUID
from datetime import datetime
from app.enums.email_sending_mode import EmailSendingMode
from app.utils.header_safety import (
    DESCRIPTION_MAX_LENGTH,
    NAME_MAX_LENGTH,
    optional_safe_text,
    require_safe_text,
)


class CampaignCreate(BaseModel):
    """Step 1 – create campaign draft"""

    name: str = Field(..., max_length=NAME_MAX_LENGTH, description="Campaign name")
    description: Optional[str] = Field(None, max_length=DESCRIPTION_MAX_LENGTH, description="Campaign description")
    goal_id: Optional[UUID] = Field(None, description="Selected goal ID")
    category_id: Optional[UUID] = Field(None, description="Selected category ID")
    tags: Optional[List[str]] = Field(default=None, description="List of tags")

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: str):
        return require_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)

    @field_validator("description")
    @classmethod
    def description_is_safe(cls, v: Optional[str]):
        return optional_safe_text(
            v, name="description", max_length=DESCRIPTION_MAX_LENGTH, allow_newlines=True
        )


class CampaignUpdate(BaseModel):
    """Allows updating basic campaign info."""
    name: Optional[str] = Field(default=None, max_length=NAME_MAX_LENGTH)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    goal_id: Optional[UUID] = None
    category_id: Optional[UUID] = None
    tags: Optional[List[str]] = None
    email_sending_mode: Optional[EmailSendingMode] = None

    @field_validator("name")
    @classmethod
    def name_is_safe(cls, v: Optional[str]):
        return optional_safe_text(v, name="name", max_length=NAME_MAX_LENGTH, allow_newlines=False)

    @field_validator("description")
    @classmethod
    def description_is_safe(cls, v: Optional[str]):
        return optional_safe_text(
            v, name="description", max_length=DESCRIPTION_MAX_LENGTH, allow_newlines=True
        )



class LeadSummary(BaseModel):
    id: UUID
    business_name: str
    industry: Optional[str]
    email: Optional[str]
    lead_score: Optional[float]

class CampaignCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: Optional[str]
    goal_id: Optional[UUID]
    category_id: Optional[UUID]
    tags: Optional[List[str]]
    status: str
    created_at: datetime
    updated_at: datetime
    launched_at: Optional[datetime] = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    description: Optional[str]
    goal_id: Optional[UUID]
    category_id: Optional[UUID]
    tags: Optional[List[str]]
    status: str
    lead_count: int
    avg_lead_score: float
    leads: List[LeadSummary] = Field(default_factory=list)
    email_sending_mode: Optional[EmailSendingMode] = None
    sender_email: Optional[str] = None
    email_subject: Optional[str] = None
    email_content: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    launched_at: Optional[datetime] = None


class PaginatedCampaignResponse(BaseModel):
    """Paginated campaigns list with metadata."""
    current_page: int
    per_page: int
    total_items: int
    total_pages: int
    data: List[CampaignResponse]



