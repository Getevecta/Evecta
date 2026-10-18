"""
Variation Engine.

Picks one variant from each independent pool (greeting, structure, CTA, closing, rhythm)
for a given lead, so a campaign's emails don't share the same shape. It decides the
*recipe*; it does not write the email (that's stage #4) — `spec_builder` packages this
selection with the tone block and rules.

How selection works:
  - Deterministic round-robin, not plain random. For each axis we shuffle the pool with a
    seed derived from (campaign_seed, axis_name), then pick `deck[index % len(deck)]`.
      * Reproducible — same (campaign_seed, index) always yields the same selection.
      * Guaranteed spread — a value can't repeat on an axis until the whole pool cycles.
      * Decorrelated axes — each axis uses its own shuffle, so they don't move in lockstep.
  - `index` is the lead's 0-based position within the campaign.
  - `campaign_seed` is any value stable per campaign (e.g. the campaign id).

Two policy hooks:
  - Personalization level limits which structures are available (free plan = fewer).
  - A light tone->CTA guard drops CTAs that contradict the chosen tone
    (e.g. the `soft_intro` tone should not push a meeting).
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field

from app.email_engine import loader

# Structures each personalization level may use. Absent / None => full catalogue.
# Only `minimal` (free plan) is narrowed, to the simplest, most reliable structures.
LEVEL_ALLOWED_STRUCTURES: dict[str, list[str]] = {
    "minimal": ["short_intro", "problem_solution"],
}

# Light tone->CTA compatibility guard: for a given tone, drop CTA variants whose text
# contains any of these keywords. Keep this minimal — only real conflicts.
TONE_CTA_EXCLUDE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "soft_intro": ("meeting",),  # a gentle first touch shouldn't push a meeting
}


@dataclass(frozen=True)
class VariantSelection:
    structure_id: str
    structure_label: str
    structure_steps: list[str] = field(default_factory=list)
    greeting: str = ""
    cta: str = ""
    closing: str = ""
    rhythm: str = ""
    tone: str = "professional"
    personalization_level: str = "standard"
    index: int = 0


def _seed_int(*parts: object) -> int:
    """Stable cross-process seed from arbitrary parts (avoids salted str hash())."""
    digest = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _pick(pool: list[str], campaign_seed: object, axis: str, index: int) -> str:
    """Deterministic round-robin pick: shuffle the pool per (seed, axis), take index-th."""
    if not pool:
        return ""
    deck = list(pool)
    random.Random(_seed_int(campaign_seed, axis)).shuffle(deck)
    return deck[index % len(deck)]


def _allowed_structure_ids(level: str, structures: dict[str, dict]) -> list[str]:
    all_ids = list(structures.keys())
    allowed = LEVEL_ALLOWED_STRUCTURES.get((level or "").strip().lower())
    if not allowed:
        return all_ids
    filtered = [sid for sid in allowed if sid in structures]
    return filtered or all_ids  # fall back to full catalogue if config is stale


def _ctas_for_tone(ctas: list[str], tone: str) -> list[str]:
    keywords = TONE_CTA_EXCLUDE_KEYWORDS.get((tone or "").strip().lower())
    if not keywords:
        return ctas
    filtered = [c for c in ctas if not any(k in c.lower() for k in keywords)]
    return filtered or ctas  # never empty the pool


def select_variants(
    *,
    campaign_seed: object,
    index: int,
    tone: str = "professional",
    personalization_level: str = "standard",
) -> VariantSelection:
    """
    Choose one variant per axis for the lead at `index` in a campaign.

    Args:
        campaign_seed: any value stable per campaign (e.g. campaign id) — fixes the shuffles.
        index: the lead's 0-based position in the campaign — drives the round-robin.
        tone: user-selected tone (one of the rules/tones/* keys).
        personalization_level: minimal | standard | deep | research (from #2).
    """
    structures = loader.get_structures()
    allowed_ids = _allowed_structure_ids(personalization_level, structures)
    structure_id = _pick(allowed_ids, campaign_seed, "structure", index)
    smeta = structures.get(structure_id, {}) if structure_id else {}

    cta_pool = _ctas_for_tone(loader.get_cta_variants(), tone)

    return VariantSelection(
        structure_id=structure_id,
        structure_label=smeta.get("label", "") if isinstance(smeta, dict) else "",
        structure_steps=list(smeta.get("steps", [])) if isinstance(smeta, dict) else [],
        greeting=_pick(loader.get_greeting_variants(), campaign_seed, "greeting", index),
        cta=_pick(cta_pool, campaign_seed, "cta", index),
        closing=_pick(loader.get_closing_variants(), campaign_seed, "closing", index),
        rhythm=_pick(loader.get_rhythm_variants(), campaign_seed, "rhythm", index),
        tone=tone,
        personalization_level=personalization_level,
        index=index,
    )
