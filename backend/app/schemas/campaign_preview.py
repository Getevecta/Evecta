from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID

class LeadSummary(BaseModel):
    id: UUID
    business_name: str
    industry: Optional[str]
    email: Optional[str]

class CampaignPreviewResponse(BaseModel):
    id: UUID
    name: str
    goal: Optional[str]
    category: Optional[str]
    draft_type: Optional[str]
    email_subject: Optional[str]
    email_content: Optional[str]
    lead_count: int
    status: str  # "ready" or "missing_draft"

