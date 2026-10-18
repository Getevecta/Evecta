from pydantic import BaseModel, Field
from typing import Any, List, Optional
from uuid import UUID


class ToneOption(BaseModel):
    id: str
    label: str


class ToneTierTone(BaseModel):
    id: str
    label: str
    description: str


class ToneTierResponse(BaseModel):
    tier_plan: str
    tier_label: str
    min_plan: str
    min_plan_rank: int
    unlocked: bool
    badge: str
    tones: List[ToneTierTone]


class PlanCapabilitiesResponse(BaseModel):
    plan: str
    max_depth: str
    label: str
    description: str
    external_research: bool
    available_fields: List[str]
    tone_options: List[ToneOption]
    tone_tiers: List[ToneTierResponse] = Field(default_factory=list)
    default_tone: str = "friendly"


class LeadPersonalizationProfile(BaseModel):
    campaign_lead_id: UUID
    lead_id: Optional[UUID] = None
    business_name: Optional[str] = None
    context_score: str
    effective_depth: str
    personalization_level: Optional[str] = None
    plan: str
    tone: str
    tone_instruction: str
    fields_available: List[str]
    context: dict[str, Any] = Field(default_factory=dict)
    fallback: Optional[str] = None
    thin_context: bool = False
    writing_spec: Optional[dict[str, Any]] = None


class PersonalizationSummary(BaseModel):
    total: int
    full: int
    partial: int
    none: int


class CampaignPersonalizationResponse(BaseModel):
    campaign_id: UUID
    tone: str
    plan_capabilities: PlanCapabilitiesResponse
    summary: PersonalizationSummary
    leads: List[LeadPersonalizationProfile]
