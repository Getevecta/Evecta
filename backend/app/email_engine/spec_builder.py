"""
Spec Builder — the output of the Template + Variation Engine (stage #3).

Combines the variant selection (variation.py), the tone block and the applicable rules
(loader.py) into a single `WritingSpec` for one lead. Stage #4 consumes this spec to build
its prompt and run its compliance gate — this module does NOT call the LLM.

It also applies the personalization level's CONTEXT DEPTH: how many lead fields are exposed
to the generator (free plan = shallow, paid = deeper). The structure-pool limiting and the
tone->CTA guard already happened inside variation.py.

`build_spec(...)` is the entry point; `WritingSpec.as_dict()` serializes it for handing
across a service boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.email_engine import loader, variation

# How much lead context each personalization level exposes to the generator.
# None => all available fields (richest). Keys match the leads dict from stage #2.
LEVEL_CONTEXT_FIELDS: dict[str, list[str] | None] = {
    "minimal": ["business_name", "industry"],
    "standard": ["business_name", "industry", "address", "services"],
    "deep": [
        "business_name", "industry", "address", "services",
        "website_summary", "business_description",
    ],
    "research": None,  # everything available on the lead
}


def _lead_context(lead: dict | None, level: str) -> dict:
    """Subset of the lead's fields allowed at this personalization level."""
    lead = lead or {}
    fields = LEVEL_CONTEXT_FIELDS.get((level or "").strip().lower(), None)
    if fields is None:  # research / unknown -> expose all non-empty fields
        return {k: v for k, v in lead.items() if v is not None}
    return {k: lead.get(k) for k in fields if lead.get(k) is not None}


def _avoid_phrases() -> list[str]:
    """Combined 'do not use' list for the generator prompt (tiering matters only to #4's gate)."""
    combined: list[str] = []
    for getter in (
        loader.get_prohibited_phrases,
        loader.get_spam_trigger_words,
        loader.get_harmful_claim_phrases,
        loader.get_aggressive_sales_phrases,
    ):
        combined.extend(getter())
    seen: set[str] = set()
    deduped: list[str] = []
    for phrase in combined:
        if phrase not in seen:
            seen.add(phrase)
            deduped.append(phrase)
    return deduped


@dataclass
class WritingSpec:
    # --- the variation recipe (from variation.py) ---
    structure_id: str
    structure_label: str
    structure_steps: list[str]
    greeting: str
    cta: str
    closing: str
    rhythm: str
    # --- tone ---
    tone: str
    tone_block: str
    # --- personalization ---
    personalization_level: str
    lead_context: dict
    user_profile: dict = field(default_factory=dict)
    company_profile: dict = field(default_factory=dict)
    # --- rules for the generator prompt ---
    avoid_phrases: list[str] = field(default_factory=list)
    openings_to_avoid: list[str] = field(default_factory=list)
    deliverability_rules: list[str] = field(default_factory=list)
    required_merge_fields: list[str] = field(default_factory=list)
    phrasing_hints: list[str] = field(default_factory=list)
    # --- reproducibility ---
    campaign_seed: str = ""
    index: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def build_spec(
    *,
    lead: dict,
    campaign_seed: object,
    index: int,
    tone: str = "professional",
    personalization_level: str = "standard",
    user_profile: dict | None = None,
    company_profile: dict | None = None,
) -> WritingSpec:
    """
    Build the writing spec for the lead at `index` in a campaign.

    Args:
        lead: the enriched lead (business_name, industry, address, services, ...).
        campaign_seed: value stable per campaign (fixes the variation shuffles).
        index: the lead's 0-based position in the campaign (drives round-robin).
        tone: user-selected tone (rules/tones/* key).
        personalization_level: minimal | standard | deep | research (from #2).
    """
    sel = variation.select_variants(
        campaign_seed=campaign_seed,
        index=index,
        tone=tone,
        personalization_level=personalization_level,
    )
    return WritingSpec(
        structure_id=sel.structure_id,
        structure_label=sel.structure_label,
        structure_steps=sel.structure_steps,
        greeting=sel.greeting,
        cta=sel.cta,
        closing=sel.closing,
        rhythm=sel.rhythm,
        tone=tone,
        tone_block=loader.get_tone(tone),
        personalization_level=personalization_level,
        lead_context=_lead_context(lead, personalization_level),
        user_profile=dict(user_profile or {}),
        company_profile=dict(company_profile or {}),
        avoid_phrases=_avoid_phrases(),
        openings_to_avoid=loader.get_openings_to_avoid(),
        deliverability_rules=loader.get_deliverability_rules(),
        required_merge_fields=loader.get_required_merge_fields(),
        phrasing_hints=loader.get_phrasing_hints(),
        campaign_seed=str(campaign_seed),
        index=index,
    )
