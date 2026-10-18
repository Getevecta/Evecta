"""
Bridge Step #2 (personalization) → Step #3 (template + variation engine).
"""
from __future__ import annotations

from typing import Any

from app.core.personalization import resolve_engine_level, tone_to_engine_key
from app.email_engine.spec_builder import WritingSpec, build_spec
from app.services.personalization_service import lead_data_from_sources, resolve_personalization


def build_writing_spec(
    *,
    lead_data: dict[str, Any],
    plan: str | None,
    tone: str | None,
    campaign_seed: object,
    index: int = 0,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
) -> WritingSpec:
    """Resolve personalization (#2) then build the writing spec (#3) for one lead."""
    profile = resolve_personalization(plan=plan, tone=tone, lead_data=lead_data)
    engine_level = resolve_engine_level(plan, profile["effective_depth"])
    engine_tone = tone_to_engine_key(profile["tone"])

    # Merge profile context into lead dict for spec_builder context filtering.
    enriched_lead = {**lead_data, **(profile.get("context") or {})}

    return build_spec(
        lead=enriched_lead,
        campaign_seed=campaign_seed,
        index=index,
        tone=engine_tone,
        personalization_level=engine_level,
        user_profile=user_profile,
        company_profile=company_profile,
    )


def writing_spec_summary(spec: WritingSpec) -> dict[str, Any]:
    """Compact preview for APIs (no full rule lists)."""
    return {
        "structure_id": spec.structure_id,
        "structure_label": spec.structure_label,
        "greeting": spec.greeting,
        "cta": spec.cta,
        "closing": spec.closing,
        "rhythm": spec.rhythm,
        "personalization_level": spec.personalization_level,
        "tone": spec.tone,
        "index": spec.index,
    }


def build_writing_spec_from_campaign_lead(
    campaign_lead,
    *,
    plan: str | None,
    tone: str | None,
    campaign_seed: object,
    index: int = 0,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
) -> WritingSpec:
    lead_data = lead_data_from_sources(campaign_lead=campaign_lead, lead=campaign_lead.lead)
    return build_writing_spec(
        lead_data=lead_data,
        plan=plan,
        tone=tone,
        campaign_seed=campaign_seed,
        index=index,
        user_profile=user_profile,
        company_profile=company_profile,
    )
