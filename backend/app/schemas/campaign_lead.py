from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class CampaignLeadCreate(BaseModel):
    """Step 2 – attach leads to a campaign."""
    lead_ids: List[UUID] = Field(..., description="List of lead UUIDs to attach")


class LeadInfo(BaseModel):
    """Lead information included in campaign lead response (live row or snapshot)."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    business_name: str
    email: Optional[str] = None
    industry: Optional[str] = None
    address: Optional[str] = None
    contact_number: Optional[str] = None
    website: Optional[str] = None
    lead_score: Optional[int] = 0
    services: Optional[str] = None
    website_summary: Optional[str] = None
    business_description: Optional[str] = None


class CampaignLeadResponse(BaseModel):
    """Campaign-lead row. Lead identity/display fields live only under ``lead``."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    campaign_id: UUID
    lead_id: Optional[UUID] = None
    created_at: datetime
    lead: Optional[LeadInfo] = None
    email_status: Optional[str] = None
    email_sent_at: Optional[datetime] = None
    context_score: Optional[str] = None
    effective_depth: Optional[str] = None
    is_user_added: bool = False

    @classmethod
    def from_orm_with_snapshot(cls, campaign_lead):
        """Create response from CampaignLead, using snapshot if the lead is deleted."""
        if campaign_lead.lead:
            source = campaign_lead.lead
            lead_info = LeadInfo(
                id=source.id,
                business_name=source.business_name,
                email=source.email,
                industry=source.industry,
                address=source.address,
                contact_number=source.contact_number,
                website=source.website,
                lead_score=source.lead_score,
                services=source.services,
                website_summary=source.website_summary,
                business_description=source.business_description,
            )
        elif campaign_lead.business_name or campaign_lead.lead_id:
            lead_info = LeadInfo(
                id=campaign_lead.lead_id or campaign_lead.id,
                business_name=campaign_lead.business_name or "Deleted Lead",
                email=campaign_lead.email,
                industry=campaign_lead.industry,
                address=campaign_lead.address,
                contact_number=campaign_lead.contact_number,
                website=campaign_lead.website,
                lead_score=campaign_lead.lead_score or 0,
                services=campaign_lead.services,
                website_summary=campaign_lead.website_summary,
                business_description=campaign_lead.business_description,
            )
        else:
            lead_info = None

        is_user_added = bool(campaign_lead.lead and campaign_lead.lead.lead_log_id is None)

        return cls(
            id=campaign_lead.id,
            campaign_id=campaign_lead.campaign_id,
            lead_id=campaign_lead.lead_id,
            created_at=campaign_lead.created_at,
            lead=lead_info,
            context_score=getattr(campaign_lead, "context_score", None),
            effective_depth=getattr(campaign_lead, "effective_depth", None),
            email_status=getattr(campaign_lead, "email_status", None),
            email_sent_at=getattr(campaign_lead, "email_sent_at", None),
            is_user_added=is_user_added,
        )
