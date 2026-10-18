import asyncio
import re
import logging
from typing import Optional, Union
from uuid import UUID
from app.services.llm import get_campaign_draft_llm
from app.services.ai.tracked_llm import tracked_ainvoke, llm_model_name
from app.services.compliance_gate import strip_html_for_check
from app.core.personalization import normalize_tone, tone_instruction
from app.email_engine.prompt_builder import format_writing_spec_prompt
from app.email_engine.spec_builder import WritingSpec
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SENDER_PLACEHOLDER_PATTERNS = (
    r"\[Your\s*Name\]",
    r"\[YourName\]",
    r"\[your\s*name\]",
    r"\[Name\]",
    r"\[Sender\s*Name\]",
)


def resolve_sender_display_name(user_profile: dict | None = None) -> str:
    """Sender signature: full_name → username → email local-part."""
    if not user_profile:
        return "Sender"
    full_name = user_profile.get("full_name")
    if full_name and str(full_name).strip():
        return str(full_name).strip()
    username = user_profile.get("username")
    if username and str(username).strip():
        return str(username).strip()
    email = user_profile.get("email")
    if email and "@" in str(email):
        local = str(email).split("@", 1)[0].strip()
        if local:
            return local.replace(".", " ").replace("_", " ").title()
    return "Sender"


def _apply_sender_name_to_email(subject: str, body: str, actual_name: str) -> tuple[str, str]:
    """Replace sender placeholders and fix signature line with the real sender name."""
    if not actual_name:
        return subject, body

    for pattern in _SENDER_PLACEHOLDER_PATTERNS:
        body = re.sub(pattern, actual_name, body, flags=re.IGNORECASE)
        subject = re.sub(pattern, actual_name, subject, flags=re.IGNORECASE)

    closing_match = re.search(
        r"(Best\s+regards,|Sincerely,|Regards,|Kind\s+regards,|Best,)\s*<p>([^<]+)</p>",
        body,
        flags=re.IGNORECASE,
    )
    if closing_match:
        closing_text = closing_match.group(1)
        signature_name = closing_match.group(2).strip()
        is_placeholder = bool(re.search(r"\[.+\]", signature_name)) or signature_name.lower() in {
            "sender",
            "[your name]",
            "[yourname]",
            "[name]",
        }
        if is_placeholder:
            body = re.sub(
                rf"({re.escape(closing_text)})\s*<p>{re.escape(signature_name)}</p>",
                rf"\1\n<p>{actual_name}</p>",
                body,
                flags=re.IGNORECASE | re.MULTILINE,
                count=1,
            )

    return subject, body


def _text_from_llm_response(response) -> str:
    """Normalize LangChain / Gemini message content (string or list of blocks) to plain text."""
    raw = getattr(response, "content", None)
    if raw is None:
        return str(response).strip()
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text") or block.get("content")
                if isinstance(t, str):
                    parts.append(t)
                elif t is not None:
                    parts.append(str(t))
            else:
                parts.append(str(block))
        return "".join(parts).strip()
    return str(raw).strip()


def _ensure_body_closing(body: str, sender_display: str) -> str:
    """
    If the model stopped early, append Best regards + signature so UX never shows a chopped email.
    """
    b = (body or "").strip()
    if not b:
        return b
    lower = b.lower()
    if "best regards" in lower or "sincerely," in lower or "kind regards" in lower:
        return b
    name = sender_display.strip() or "[Your Name]"
    return (
        b.rstrip()
        + "\n<p>I'd welcome a brief reply if this resonates.</p>\n"
        + "<p>Best regards,</p>\n"
        + f"<p>{name}</p>"
    )


def _strip_meta_copywriter_leadin(body: str) -> str:
    """Drop <p> blocks that read as meta 'copywriter' voice (anywhere in body), not as the sender."""
    if not body:
        return body
    meta_pat = re.compile(
        r"as a b2b|email copywriter|professional copywriter|as an ai|i am (?:an? )?ai",
        re.IGNORECASE,
    )

    def _drop_if_meta(m: re.Match) -> str:
        return "" if meta_pat.search(m.group(0)) else m.group(0)

    out = re.sub(
        r"<p>.*?</p>\s*",
        _drop_if_meta,
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Truncated model output: unclosed <p>… copywriter …
    out = re.sub(
        r"<p>\s*[^<]*?(?:as a b2b|email copywriter|professional copywriter)[^<]*(?:</p>)?",
        "",
        out,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return out.strip()


def _is_unclear_description(description: str | None) -> bool:
    """True only for greetings or empty input — never infer a topic when the user gave a real brief."""
    if not description:
        return True

    text = description.strip()
    if not text:
        return True

    description_lower = text.lower()

    unclear_patterns = [
        r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))[\s,\.!]*$',
        r'^(hi|hello|hey)[\s,\.!]*$',
    ]
    if any(re.match(pattern, description_lower) for pattern in unclear_patterns):
        return True

    # Any substantive brief (≥20 chars) is treated as clear — follow it literally.
    if len(text) >= 20:
        return False

    # Short briefs with instruction words are still clear (e.g. "email about ads placement").
    instruction_markers = (
        "write", "email", "mail", "say", "about", "for", "ask", "offer", "pitch",
        "ads", "ad ", "placement", "sell", "promot", "reach", "contact", "mention",
        "partnership", "partner", "collaborat", "demo", "meeting", "introduc",
        "hire", "recruit", "invest", "launch", "service", "product", "consult",
        "advertis", "sponsor", "banner", "campaign",
    )
    if any(marker in description_lower for marker in instruction_markers):
        return False

    return len(text) < 12


def _user_intent_section(description: str | None, *, label: str = "USER REQUEST") -> str:
    """Prompt block that forces the model to follow the user's brief."""
    if not description or not description.strip():
        return f'{label} (primary — follow this precisely):\n"Professional B2B outreach"\n'

    brief = description.strip().replace('"', "'")
    return f"""{label} (HIGHEST PRIORITY — this IS the email topic; nothing else overrides it):
"{brief}"

MANDATORY — BRIEF FIDELITY:
- Write EXACTLY what the user asked for. Do NOT invent a different topic, offer, product pitch, or partnership angle.
- Treat the quoted brief as the source of truth. Expand and polish THEIR words into a full email — do not replace them.
- If the brief is awkward, incomplete, or hard to parse: keep their intent and rephrase for clarity. NEVER discard it and write a generic B2B outreach email.
- Do NOT substitute a partnership pitch, product intro, demo ask, or company value-prop unless the brief explicitly asks for that.
- If the brief mentions ads, ad placement, sponsorship, collaboration, hiring, or any specific goal — that MUST be the core of subject, body, and CTA.
- Sender/company profile is identity only (who is writing) — never replace the user's topic with the company's products or services.
- Subject, opening, main message, and call-to-action MUST directly reflect this brief. A reader should recognize the brief in the email.
"""


def _profile_context_section(
    *,
    user_profile: dict | None,
    company_profile: dict | None,
    sender_name: str,
    is_unclear: bool,
) -> str:
    """Background sender context — supplementary to the user's brief."""
    if not user_profile and not company_profile:
        return ""

    context_parts = []
    if user_profile:
        context_parts.append(f"Sender Name: {sender_name}")
        if user_profile.get("bio"):
            context_parts.append(f"About Sender: {user_profile.get('bio')}")
        if user_profile.get("department"):
            context_parts.append(f"Department: {user_profile.get('department')}")
        if user_profile.get("location"):
            context_parts.append(f"Location: {user_profile.get('location')}")

    if company_profile:
        if company_profile.get("company_name"):
            context_parts.append(f"Company: {company_profile.get('company_name')}")
        if company_profile.get("company_description"):
            context_parts.append(f"Company Description: {company_profile.get('company_description')}")
        if company_profile.get("products_and_services"):
            products = company_profile.get("products_and_services", [])
            if isinstance(products, list) and products:
                products_str = ", ".join([str(p) for p in products[:5]])
                context_parts.append(f"Products/Services: {products_str}")

    if not context_parts:
        return ""

    section = (
        "\n\nSENDER BACKGROUND (identity only — who is sending; do NOT change the email topic):\n"
        + "\n".join(context_parts)
    )
    # Never invite the model to invent a topic from company profile — that overrides user context.
    section += (
        "\n\nDo NOT use company products/services as the email topic unless the USER REQUEST / brief "
        "explicitly asks for that. Use this block only for the sender's name and light identity."
    )
    if is_unclear:
        section += (
            "\nThe brief is very short — still do NOT invent a product/partnership pitch from this background; "
            "write a short professional outreach that stays faithful to whatever words the user provided."
        )
    return section


def _plain_text_snippet(html_or_text: str | None, *, max_chars: int = 400) -> str:
    """Strip HTML and collapse whitespace for prompt injection."""
    if not html_or_text or not str(html_or_text).strip():
        return ""
    plain = strip_html_for_check(str(html_or_text))
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) > max_chars:
        plain = plain[: max_chars - 1].rstrip() + "…"
    return plain

async def generate_campaign_ai_draft(
    campaign_name: str,
    tone: str,
    description: str | None,
    goal: str | None = None,
    category: str | None = None,
    leads_sample: list[dict] | None = None,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
    writing_spec: WritingSpec | dict | None = None,
    user_id: Optional[Union[str, UUID]] = None,
):
    """
    Generate a B2B email draft using Gemini (via LangChain) following a strict 7-part format
    with greeting at the start and closing at the end, wrapping all content inside <p> tags for HTML emails.
    Subject line is dynamically generated as a short catchy line under 10 words.
    """

    # Normalize tone — prefer markdown tone block from writing spec when present
    tone_key = normalize_tone(tone)
    if writing_spec:
        if isinstance(writing_spec, WritingSpec):
            spec_tone_block = writing_spec.tone_block
        else:
            spec_tone_block = writing_spec.get("tone_block") or ""
        tone_instruction_text = spec_tone_block.strip() or tone_instruction(tone_key)
    else:
        tone_instruction_text = tone_instruction(tone_key)

    writing_spec_section = ""
    if writing_spec:
        writing_spec_section = "\n\n" + format_writing_spec_prompt(writing_spec)

    # Build lead sample context (optional) — includes personalization depth hints
    lead_summary = ""
    if leads_sample:
        sample_lines = []
        for l in leads_sample[:3]:
            line = f"- {l.get('business_name', 'a company')} ({l.get('industry', 'industry')})"
            depth = l.get("effective_depth")
            ctx = l.get("context") or {}
            if depth and depth != "basic":
                extras = []
                if ctx.get("website_summary"):
                    extras.append(f"summary: {ctx['website_summary']}")
                if ctx.get("services"):
                    extras.append(f"services: {ctx['services']}")
                if ctx.get("business_description"):
                    extras.append(f"about: {ctx['business_description']}")
                if extras:
                    line += " — " + "; ".join(extras[:2])
            sample_lines.append(line)
        lead_summary = "\n".join(sample_lines)

    sender_name = resolve_sender_display_name(user_profile)

    # Check if description is unclear and build user context
    is_unclear = _is_unclear_description(description)
    user_context_section = _profile_context_section(
        user_profile=user_profile,
        company_profile=company_profile,
        sender_name=sender_name,
        is_unclear=is_unclear,
    )
    user_intent_section = _user_intent_section(description)

    # Never tell the model to invent from company profile — that causes context drift.
    unclear_note = (
        "\nUser input is very short — expand ONLY the words they wrote into a short professional email. "
        "Do NOT invent a product pitch, partnership offer, or company value-prop from SENDER BACKGROUND.\n"
        if is_unclear
        else ""
    )
    prompt = f"""You are writing an email AS THE SENDER (a real person reaching out to a prospect). {tone_instruction_text}

{user_intent_section}{unclear_note}{user_context_section}
{writing_spec_section}

Rules:
- The USER REQUEST above is the email topic — follow it literally. Never write your own unrelated pitch.
- If you are unsure what the brief means: rephrase and expand the user's own words. Never abandon the brief for a generic B2B email.
- NEVER write in meta voice: do not say you are a copywriter, writer, or AI. Do not start with "As a B2B…" or "I'm impressed by your work as a…". Write the email directly to the recipient.
- Writing spec (if present) defines paragraph order and tone only — not the subject matter. Fill every step with USER REQUEST content.
- Output plain structure: first line exactly like `Subject: ...` (≤50 chars, professional, no spam words like free/urgent/guarantee/click here/act now).
- Then body as HTML `<p>...</p>` lines only (no markdown fences). Complete email: ~100–160 words, multiple `<p>` lines (not one giant paragraph). Finish every sentence; do not stop mid-sentence.
- MUST include ALL THREE merge fields exactly: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}}.
  • Greeting: Hi {{{{ business_name }}}}, or Hello {{{{ business_name }}}},
  • Use {{{{ industry }}}} and {{{{ address }}}} naturally in body (not only subject).
  • NEVER hardcode a specific industry name (e.g. "pharmacy", "restaurant", "healthcare") or a specific location/city/region (e.g. "London", "New York", "Mumbai"). Use ONLY the {{{{ industry }}}} and {{{{ address }}}} placeholders — they will be replaced with the real values at send time.
- Spam-safe: no emojis, no ALL CAPS, avoid "Hope this finds you well" as opening line; specific opener.
- MANDATORY closing (last two lines of body): <p>Best regards,</p> then <p>{sender_name}</p> — signature EXACTLY "{sender_name}" (no fake names). Do not omit the closing.

Audience hint:
{lead_summary or "- B2B companies in varied industries."}

Output order:
Subject: ...
<p>Hi {{{{ business_name }}}},</p>
<p>...</p>
...
<p>Best regards,</p>
<p>{sender_name}</p>
"""

    llm = get_campaign_draft_llm()
    settings = get_settings()
    
    # Two attempts so a transient Gemini/network blip can actually retry.
    # range(1) made the backoff branch (attempt < max_retries - 1) unreachable.
    max_retries = 2
    base_delay = 0.35
    timeout_seconds = 55
    response = None
    
    for attempt in range(max_retries):
        try:
            # Use asyncio.wait_for to add timeout
            response = await asyncio.wait_for(
                tracked_ainvoke(
                    llm=llm,
                    prompt=prompt,
                    provider="gemini",
                    model=llm_model_name(llm, fallback=settings.GEMINI_MODEL or "gemini-2.5-flash"),
                    feature="campaign_email",
                    user_id=user_id,
                ),
                timeout=timeout_seconds
            )
            break  # Success, exit retry loop
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"AI generation timeout (attempt {attempt + 1}/{max_retries}), retrying in {delay}s...")
                await asyncio.sleep(delay)
                continue
            else:
                raise RuntimeError(f"AI generation failed: Timeout after {timeout_seconds}s after {max_retries} attempts")
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"AI generation error (attempt {attempt + 1}/{max_retries}): {str(e)}, retrying in {delay}s...")
                await asyncio.sleep(delay)
                continue
            else:
                raise RuntimeError(f"AI generation failed after {max_retries} attempts: {str(e)}")
    
    if response is None:
        raise RuntimeError("AI generation failed: No response received after all retries")

    text = _text_from_llm_response(response)

    # Extract subject line generated by AI
    subject_line = next(
        (l.replace("Subject:", "").strip() for l in text.split("\n") if l.lower().startswith("subject")),
        None
    )

    # Ensure subject is under 10 words
    if subject_line:
        words = subject_line.split()
        if len(words) > 10:
            subject_line = " ".join(words[:10])
    else:
        subject_line = "New update for you"  # fallback

    # Ensure each line starts and ends with <p>...</p>
    body_lines = [
        line if line.startswith("<p>") and line.endswith("</p>") else f"<p>{line}</p>"
        for line in text.split("\n") if line.strip() and not line.lower().startswith("subject:")
    ]
    body = "\n".join(body_lines).strip()
    body = _strip_meta_copywriter_leadin(body)
    body = _ensure_body_closing(body, sender_name)

    actual_name = resolve_sender_display_name(user_profile)
    subject_line, body = _apply_sender_name_to_email(subject_line, body, actual_name)
    
    # Backwards-compatibility: if any old company-name placeholders remain, replace them with the real company name
    if company_profile and company_profile.get('company_name'):
        actual_company = company_profile.get('company_name')
        body = re.sub(r'\[\s*Your\s*Company\s*Name\s*\]', actual_company, body, flags=re.IGNORECASE)
        body = re.sub(r'\[\s*Company\s*Name\s*\]', actual_company, body, flags=re.IGNORECASE)
        subject_line = re.sub(r'\[\s*Your\s*Company\s*Name\s*\]', actual_company, subject_line, flags=re.IGNORECASE)
        subject_line = re.sub(r'\[\s*Company\s*Name\s*\]', actual_company, subject_line, flags=re.IGNORECASE)

    return subject_line[:255], body


def _flatten_lead_context(lead_data: dict) -> dict:
    """Merge top-level lead fields with nested personalization context."""
    flat: dict = {}
    for key, value in (lead_data or {}).items():
        if key == "context" or value is None:
            continue
        if str(value).strip():
            flat[key] = value
    for key, value in ((lead_data or {}).get("context") or {}).items():
        if value is not None and str(value).strip() and key not in flat:
            flat[key] = value
    return flat


def _format_lead_facts_block(lead_data: dict) -> str:
    """Human-readable lead facts for the per-lead generation prompt."""
    flat = _flatten_lead_context(lead_data)
    lines: list[str] = []
    if flat.get("business_name"):
        lines.append(f"- Company name: {flat['business_name']}")
    if flat.get("industry"):
        lines.append(f"- Industry: {flat['industry']}")
    if flat.get("address"):
        lines.append(f"- Location: {flat['address']}")
    if flat.get("website"):
        lines.append(f"- Website: {flat['website']}")
    if flat.get("services"):
        lines.append(f"- Services / offerings: {flat['services']}")
    if flat.get("website_summary"):
        lines.append(f"- Website summary: {flat['website_summary']}")
    if flat.get("business_description"):
        lines.append(f"- About the business: {flat['business_description']}")
    if not lines:
        lines.append("- Limited lead data — write a professional outreach email using the company name only.")
    return "\n".join(lines)


def _prior_emails_avoid_section(prior_bodies: list[str]) -> str:
    if not prior_bodies:
        return ""
    snippets: list[str] = []
    for idx, body in enumerate(prior_bodies[-3:], 1):
        plain = strip_html_for_check(body or "")[:220].replace("\n", " ").strip()
        if plain:
            snippets.append(f"  {idx}. {plain}")
    if not snippets:
        return ""
    return (
        "\n\nEMAILS ALREADY WRITTEN FOR OTHER LEADS IN THIS CAMPAIGN "
        "(vary opener and wording only — keep the SAME purpose as USER CAMPAIGN BRIEF; do not reuse phrasing):\n"
        + "\n".join(snippets)
    )


def _apply_lead_placeholders(text: str, lead_data: dict) -> str:
    """Replace any remaining merge fields with this lead's actual values."""
    if not text:
        return text
    flat = _flatten_lead_context(lead_data)
    out = text
    for key, value in flat.items():
        if value is None or not str(value).strip():
            continue
        val = str(value).strip()
        out = out.replace(f"{{{{ {key} }}}}", val)
        out = out.replace(f"{{{{{key}}}}}", val)
    return out


async def generate_per_lead_email(
    *,
    tone: str,
    description: str | None,
    lead_data: dict,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
    writing_spec: WritingSpec | dict | None = None,
    reference_subject: str | None = None,
    reference_body: str | None = None,
    prior_bodies: list[str] | None = None,
    lead_index: int = 0,
    compliance_feedback: str | None = None,
    similarity_feedback: str | None = None,
    user_id: Optional[Union[str, UUID]] = None,
) -> tuple[str, str]:
    """
    Generate a unique outreach email for one lead (Step 4).
    Uses the template + variation writing spec and lead enrichment context.
    """
    tone_key = normalize_tone(tone)
    if writing_spec:
        if isinstance(writing_spec, WritingSpec):
            spec_tone_block = writing_spec.tone_block
        else:
            spec_tone_block = writing_spec.get("tone_block") or ""
        tone_instruction_text = spec_tone_block.strip() or tone_instruction(tone_key)
    else:
        tone_instruction_text = tone_instruction(tone_key)

    writing_spec_section = ""
    if writing_spec:
        writing_spec_section = "\n\n" + format_writing_spec_prompt(writing_spec)

    lead_summary = _format_lead_facts_block(lead_data)
    flat_lead = _flatten_lead_context(lead_data)
    lead_name = flat_lead.get("business_name") or "the recipient"

    is_unclear = _is_unclear_description(description)
    sender_name = resolve_sender_display_name(user_profile)
    user_context_section = _profile_context_section(
        user_profile=user_profile,
        company_profile=company_profile,
        sender_name=sender_name,
        is_unclear=is_unclear,
    )
    user_intent_section = _user_intent_section(description, label="USER CAMPAIGN BRIEF")

    reference_section = ""
    ref_body_snippet = _plain_text_snippet(reference_body, max_chars=420)
    if reference_subject or ref_body_snippet:
        parts = [
            "\n\nAPPROVED CAMPAIGN DRAFT (topic + tone anchor — USER CAMPAIGN BRIEF still wins if they conflict):",
        ]
        if reference_subject:
            parts.append(f"Subject: {reference_subject[:120]}")
        if ref_body_snippet:
            parts.append(f"Body gist: {ref_body_snippet}")
        parts.append(
            "Keep the same purpose and message as this draft and the brief. "
            "Personalize for THIS lead only — do not invent a new offer or pitch."
        )
        reference_section = "\n".join(parts)

    prior_section = _prior_emails_avoid_section(prior_bodies or [])

    compliance_section = ""
    if compliance_feedback:
        compliance_section = (
            "\n\nPREVIOUS DRAFT FAILED SPAM/COMPLIANCE CHECK — rewrite to fix:\n"
            f"{compliance_feedback}\n"
            "Avoid spam triggers: free, urgent, guarantee, click here, act now, ALL CAPS, emojis. "
            "Keep the SAME topic as the USER CAMPAIGN BRIEF — only fix deliverability wording."
        )

    similarity_section = ""
    if similarity_feedback:
        similarity_section = (
            "\n\nPREVIOUS DRAFT WAS REJECTED — TOO SIMILAR to an email already written for "
            "another lead in this campaign (this was NOT a spam problem). That email starts:\n"
            f'"{similarity_feedback}"\n'
            "Rewrite with a clearly different opener and phrasing — keep the SAME purpose as the USER CAMPAIGN BRIEF."
        )

    unclear_note = (
        "\nUser brief is very short — expand ONLY their words into a short professional email. "
        "Do NOT invent a product/partnership pitch from SENDER BACKGROUND.\n"
        if is_unclear
        else ""
    )

    prompt = f"""You are writing a unique outreach email AS THE SENDER to ONE specific prospect.
Lead #{lead_index + 1} in this campaign — this email must read differently from every other lead.
{tone_instruction_text}

{user_intent_section}{unclear_note}{user_context_section}
{reference_section}
{prior_section}
{compliance_section}{similarity_section}
{writing_spec_section}

THIS LEAD — use these real facts in the email (name, location, services, summary, etc.):
{lead_summary}

Rules:
- The USER CAMPAIGN BRIEF defines purpose — every paragraph must serve that intent; do not invent a different offer.
- If the brief is unclear: rephrase the user's own words — never replace them with a generic B2B pitch.
- Writing spec (if present) is paragraph order and tone only — fill each step with content from the USER CAMPAIGN BRIEF.
- Write directly to {lead_name}; no meta copywriter voice.
- First line: `Subject: ...` (≤50 chars, professional, mention something specific to THIS lead when possible).
- Body: HTML `<p>...</p>` lines only. ~100–160 words. Complete sentences.
- Personalize using THIS lead's company name, industry, location, and enrichment details above.
- Do NOT use {{{{ merge_field }}}} placeholders — write the final email with real lead details filled in.
- Do NOT reuse the same opener, value prop, or CTA as other leads in this campaign.
- Weave in lead-specific context (services, website summary, about) when provided — only as personalization, not as a new topic.
- Spam-safe: no emojis, no ALL CAPS, no "click here", "act now", "guaranteed", or "free" hype.
- Closing: <p>Best regards,</p> then <p>{sender_name}</p>

Output:
Subject: ...
<p>Hi {lead_name},</p>
...
<p>Best regards,</p>
<p>{sender_name}</p>
"""

    llm = get_campaign_draft_llm()
    settings = get_settings()
    response = await asyncio.wait_for(
        tracked_ainvoke(
            llm=llm,
            prompt=prompt,
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL or "gemini-2.5-flash"),
            feature="campaign_email",
            user_id=user_id,
        ),
        timeout=55,
    )
    text = _text_from_llm_response(response)

    subject_line = next(
        (l.replace("Subject:", "").strip() for l in text.split("\n") if l.lower().startswith("subject")),
        None,
    )
    if subject_line:
        words = subject_line.split()
        if len(words) > 10:
            subject_line = " ".join(words[:10])
    else:
        subject_line = f"Quick idea for {lead_name}"

    body_lines = [
        line if line.startswith("<p>") and line.endswith("</p>") else f"<p>{line}</p>"
        for line in text.split("\n")
        if line.strip() and not line.lower().startswith("subject:")
    ]
    body = "\n".join(body_lines).strip()
    body = _strip_meta_copywriter_leadin(body)
    body = _ensure_body_closing(body, sender_name)

    actual_name = resolve_sender_display_name(user_profile)
    subject_line, body = _apply_sender_name_to_email(subject_line, body, actual_name)

    subject_line = _apply_lead_placeholders(subject_line, lead_data)
    body = _apply_lead_placeholders(body, lead_data)

    return subject_line[:255], body


def get_fallback_template(
    description: str | None = None,
    user_profile: dict | None = None,
    company_profile: dict | None = None,
) -> tuple[str, str]:
    """
    Generate a fallback email template when AI generation fails.
    Returns (subject, content) tuple with required placeholders.
    Anchors on the user's brief so fallback never invents an unrelated pitch.
    """
    sender_name = resolve_sender_display_name(user_profile)
    brief = (description or "").strip()
    brief_lower = brief.lower()
    brief_safe = re.sub(r"<[^>]+>", "", brief).replace('"', "'")
    if len(brief_safe) > 220:
        brief_safe = brief_safe[:219].rstrip() + "…"

    # Prefer a subject that echoes the brief when we have one.
    if brief and not _is_unclear_description(description):
        words = [w for w in re.findall(r"[A-Za-z0-9']+", brief) if len(w) > 2][:6]
        subject = " ".join(words).capitalize() if words else f"Regarding {{{{ business_name }}}}"
        if len(subject) > 50:
            subject = subject[:50].rstrip()
    else:
        subject = f"Quick note for {{{{ business_name }}}}"

    content_parts = [
        f"<p>Hello {{{{ business_name }}}},</p>",
        f"<p>I noticed {{{{ business_name }}}} in the {{{{ industry }}}} space ({{{{ address }}}}) and wanted to reach out.</p>",
    ]

    if brief and not _is_unclear_description(description):
        # Embed the user's context so fallback stays on-topic even without the LLM.
        content_parts.append(
            f"<p>I am writing about: {brief_safe}</p>"
        )
        if any(k in brief_lower for k in ("ads", "ad placement", "advertis", "sponsor", "banner")):
            content_parts.append(
                "<p>I would welcome a short conversation about advertising placement options "
                "and whether there is a mutual fit.</p>"
            )
        elif any(k in brief_lower for k in ("partner", "collaborat", "alliance")):
            content_parts.append(
                "<p>I would welcome a short conversation to see if a partnership along these lines makes sense.</p>"
            )
        else:
            content_parts.append(
                "<p>Happy to share more detail in a brief reply if this is relevant for your team.</p>"
            )
    else:
        content_parts.append(
            "<p>I wanted to connect with a short professional note. "
            "If a brief conversation would be useful, I am happy to share more.</p>"
        )

    content_parts.extend([
        "<p>Best regards,</p>",
        f"<p>{sender_name}</p>",
    ])

    return subject, "\n".join(content_parts)
