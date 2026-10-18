"""
Turn a WritingSpec into prompt text for stage #4 (LLM generation).
"""
from __future__ import annotations

from app.email_engine.spec_builder import WritingSpec


def _lines(label: str, items: list[str], *, max_items: int | None = None) -> str:
    if not items:
        return ""
    slice_ = items[:max_items] if max_items else items
    body = "\n".join(f"- {x}" for x in slice_)
    return f"{label}:\n{body}\n"


def format_writing_spec_prompt(spec: WritingSpec | dict) -> str:
    """Render the writing spec as structured instructions for the LLM."""
    if isinstance(spec, WritingSpec):
        d = spec.as_dict()
    else:
        d = dict(spec)

    steps = d.get("structure_steps") or []
    steps_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(steps))

    lead_ctx = d.get("lead_context") or {}
    lead_lines = "\n".join(f"- {k}: {v}" for k, v in lead_ctx.items() if v)

    parts = [
        "WRITING SPEC (SHAPE ONLY — paragraph order and tone. CONTENT must come from the USER REQUEST / campaign brief above):",
        "Never invent a value proposition, product pitch, or partnership offer that is not in the USER REQUEST.",
        f"Structure format: {d.get('structure_label') or d.get('structure_id', '')}",
        f"Follow these paragraph steps in order (fill each with USER REQUEST content, not a generic pitch):\n{steps_text}"
        if steps_text
        else "",
        f"Greeting style: {d.get('greeting', '')}",
        f"Call to action: {d.get('cta', '')} — align CTA with the USER REQUEST goal",
        f"Closing style: {d.get('closing', '')}",
        f"Rhythm / phrasing feel: {d.get('rhythm', '')}",
        "",
        "TONE GUIDANCE:",
        d.get("tone_block") or "",
        "",
        f"Personalization level: {d.get('personalization_level', 'standard')}",
        f"Lead context to weave in naturally (do not invent beyond this):\n{lead_lines}"
        if lead_lines
        else "Lead context: use merge fields only — no extra lead detail available.",
        "",
        _lines("Phrasing hints", d.get("phrasing_hints") or [], max_items=6),
        _lines("Openings to avoid", d.get("openings_to_avoid") or [], max_items=8),
        _lines("Deliverability rules", d.get("deliverability_rules") or [], max_items=8),
        _lines("Never use these phrases", d.get("avoid_phrases") or [], max_items=20),
        _lines(
            "Required merge fields (include exactly)",
            d.get("required_merge_fields") or [],
        ),
    ]
    return "\n".join(p for p in parts if p and p.strip())
