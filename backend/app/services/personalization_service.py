"""
Personalization Level Engine — score lead context and resolve per-lead profiles.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.core.personalization import (
    DEFAULT_TONE,
    effective_depth,
    fields_for_depth,
    normalize_plan,
    normalize_tone,
    plan_capabilities,
    tone_instruction,
    ContextScore,
    resolve_engine_level,
)
from app.models.campaign import Campaign
from app.models.campaign_lead import CampaignLead
from app.models.user import User


def _non_empty(value: Any) -> bool:
    return bool(value and str(value).strip())


def score_lead_context(lead_data: dict[str, Any]) -> str:
    """
    Score how much personalization context is available for a lead.

    Returns: 'full' | 'partial' | 'none'
    """
    context_fields = (
        lead_data.get("website_summary"),
        lead_data.get("business_description"),
        lead_data.get("services"),
    )
    present = sum(1 for f in context_fields if _non_empty(f))
    if present >= 3:
        return ContextScore.FULL.value
    if present >= 1:
        return ContextScore.PARTIAL.value
    return ContextScore.NONE.value


def lead_data_from_sources(
    *,
    campaign_lead: CampaignLead | None = None,
    lead=None,
) -> dict[str, Any]:
    """Build a flat dict for scoring — prefer live lead, then campaign snapshot."""
    src = lead if lead is not None else campaign_lead
    if src is None:
        return {}

    def _get(attr: str):
        if lead is not None and getattr(lead, attr, None) is not None:
            return getattr(lead, attr)
        if campaign_lead is not None and getattr(campaign_lead, attr, None) is not None:
            return getattr(campaign_lead, attr)
        return None

    return {
        "business_name": _get("business_name"),
        "industry": _get("industry"),
        "address": _get("address"),
        "website": _get("website"),
        "services": _get("services"),
        "website_summary": _get("website_summary"),
        "business_description": _get("business_description"),
    }


def resolve_personalization(
    *,
    plan: str | None,
    tone: str | None,
    lead_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Resolve the personalization profile for one lead.

    When lead context is thin, ``fallback`` is ``sender_profile`` so generation
    leans on the user's company profile instead of inventing lead detail.
    """
    context_score = score_lead_context(lead_data)
    depth = effective_depth(plan, context_score)
    allowed_fields = fields_for_depth(depth)
    context_payload = {
        k: lead_data.get(k)
        for k in allowed_fields
        if _non_empty(lead_data.get(k))
    }
    fallback = "sender_profile" if context_score == ContextScore.NONE.value else None
    normalized_tone = normalize_tone(tone)

    return {
        "context_score": context_score,
        "effective_depth": depth,
        "plan": normalize_plan(plan),
        "tone": normalized_tone,
        "tone_instruction": tone_instruction(normalized_tone),
        "fields_available": list(allowed_fields),
        "context": context_payload,
        "fallback": fallback,
        "thin_context": context_score != ContextScore.FULL.value,
    }


def snapshot_context_fields(lead) -> dict[str, Any]:
    """Context columns to copy onto CampaignLead when syncing."""
    return {
        "services": getattr(lead, "services", None),
        "website_summary": getattr(lead, "website_summary", None),
        "business_description": getattr(lead, "business_description", None),
    }


async def get_campaign_personalization_preview(
    campaign_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    tone: str | None = None,
) -> dict[str, Any]:
    """Return plan capabilities and per-lead personalization profiles for a campaign."""
    from app.services.writing_spec_service import (
        build_writing_spec_from_campaign_lead,
        writing_spec_summary,
    )

    campaign = await db.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.user_id == user_id)
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found or unauthorized.")

    user = await db.get(User, user_id)
    plan = user.plan if user else "free"
    resolved_tone = normalize_tone(tone or campaign.tone or DEFAULT_TONE)

    result = await db.scalars(
        select(CampaignLead)
        .where(CampaignLead.campaign_id == campaign_id)
        .options(selectinload(CampaignLead.lead))
    )
    campaign_leads = result.all()

    leads_preview = []
    for idx, cl in enumerate(campaign_leads):
        lead_data = lead_data_from_sources(campaign_lead=cl, lead=cl.lead)
        profile = resolve_personalization(
            plan=plan,
            tone=resolved_tone,
            lead_data=lead_data,
        )
        writing_spec = build_writing_spec_from_campaign_lead(
            cl,
            plan=plan,
            tone=resolved_tone,
            campaign_seed=str(campaign_id),
            index=idx,
        )
        leads_preview.append(
            {
                "campaign_lead_id": cl.id,
                "lead_id": cl.lead_id,
                "business_name": cl.business_name or lead_data.get("business_name"),
                "personalization_level": resolve_engine_level(plan, profile["effective_depth"]),
                "writing_spec": writing_spec_summary(writing_spec),
                **profile,
            }
        )

    scores = [p["context_score"] for p in leads_preview]
    summary = {
        "total": len(leads_preview),
        "full": scores.count("full"),
        "partial": scores.count("partial"),
        "none": scores.count("none"),
    }

    return {
        "campaign_id": campaign_id,
        "tone": resolved_tone,
        "plan_capabilities": plan_capabilities(plan),
        "summary": summary,
        "leads": leads_preview,
    }
