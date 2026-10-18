from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, ConfigDict

def lead_to_response(lead) -> "LeadResponse":
    """Build API response with derived flags."""
    return LeadResponse.model_validate(lead).model_copy(
        update={"is_user_added": lead.lead_log_id is None}
    )

class LeadBase(BaseModel):
    business_name: str
    industry: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    lead_score: Optional[int] = Field(default=0, ge=0, le=100)
    # Scraped personalization context (filled during enrichment).
    services: Optional[str] = None
    website_summary: Optional[str] = None
    business_description: Optional[str] = None


class LeadCreate(LeadBase):
    pass

class LeadUpdate(BaseModel):
    business_name: Optional[str] = None
    industry: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    website: Optional[str] = None
    lead_score: Optional[int] = Field(default=None, ge=0, le=100)

class LeadResponse(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    starred: bool = False
    created_at: datetime
    updated_at: datetime
    # Outreach information
    last_contacted: Optional[datetime] = None
    campaign_status: Optional[str] = None  # 'draft', 'ongoing', 'completed', or None if not in any campaign
    outreach_status: Optional[str] = None  # 'not_started', 'contacted', 'replied', 'no_response'
    # True when lead was added manually or via Excel (not promoted from lead generation).
    is_user_added: bool = False




class LeadLogLeadResponse(LeadBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime



class LeadLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    chat_title: str
    query: str
    promoted: bool
    status: str = "active"   # "gathering" | "active" | "empty" | "failed" — for cold-load polling
    created_at: datetime
    leads: List[LeadLogLeadResponse] = Field(default_factory=list)


class LeadLogListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_title: str
    query: str
    promoted: bool
    created_at: datetime
    lead_count: int = 0

class PromoteLeadsRequest(BaseModel):
    """Schema for promoting selected or all leads from a log."""
    selected_lead_ids: Optional[List[UUID]] = None

class BulkDeleteLeadsRequest(BaseModel):
    """Schema for deleting many leads in one request.

    Capped at 1000 ids per request — bounds the request body, the transaction
    size, and the cascade fan-out (leads cascade to email_activity/email_job/
    email_message and SET NULL on campaign_leads/campaign_lead_email). Requests
    over the cap are rejected with a 422 before any DB work.
    """
    lead_ids: List[UUID] = Field(..., min_length=1, max_length=1000)


class BulkGetLeadsRequest(BaseModel):
    """Schema for fetching many leads by id in one request."""
    lead_ids: List[UUID] = Field(..., min_length=1, max_length=1000)