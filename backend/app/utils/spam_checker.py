import asyncio
import json
import logging
import re
import hashlib
import weakref
from typing import Dict, Any, Tuple, Optional
from fastapi import HTTPException
from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import get_settings
from app.services.ai.tracked_llm import tracked_ainvoke, llm_model_name

settings = get_settings()
logger = logging.getLogger(__name__)
# Prefer APP_GEMINI_SPAM_CHECK_MODEL, else main APP_GEMINI_MODEL (2.0-flash is unavailable for many new API keys).
_raw_spam = (getattr(settings, "GEMINI_SPAM_CHECK_MODEL", None) or "").strip()
_spam_model = _raw_spam or (getattr(settings, "GEMINI_MODEL", None) or "").strip() or "gemini-2.5-flash"
def _build_spam_llm(max_output_tokens: int) -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=_spam_model,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=0.1,
        convert_system_message_to_human=True,
        max_output_tokens=max_output_tokens,
    )


# The Gemini client binds its async gRPC channel to the event loop of its first call.
# Celery tasks each run in a fresh event loop that is closed afterwards, so a client
# shared across tasks fails every later call ("Spam check failed"). Keep one pair per
# loop: the API's single loop reuses it; each Celery task gets its own.
_spam_llms_by_loop: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, tuple]" = weakref.WeakKeyDictionary()


def _spam_llms() -> tuple[ChatGoogleGenerativeAI, ChatGoogleGenerativeAI]:
    """(full spam-check client, short score-only client) for the running event loop."""
    loop = asyncio.get_running_loop()
    llms = _spam_llms_by_loop.get(loop)
    if llms is None:
        # Score-only: short JSON (spam_score + risk_level); budget avoids truncated outputs.
        llms = (_build_spam_llm(8192), _build_spam_llm(1024))
        _spam_llms_by_loop[loop] = llms
    return llms


def _spam_check_llm() -> ChatGoogleGenerativeAI:
    return _spam_llms()[0]


def _spam_score_only_llm() -> ChatGoogleGenerativeAI:
    return _spam_llms()[1]

_spam_check_cache: Dict[str, Dict[str, Any]] = {}

# Smaller slices = fewer tokens = lower latency (full text still used for cache key).
_SUBJ_MAX_FAST = 240
_BODY_MAX_FAST = 4500
_SUBJ_MAX_FULL = 500
_BODY_MAX_FULL = 10000


def _truncate_for_spam_llm(subject: str, body: str, fast_mode: bool) -> Tuple[str, str]:
    smax = _SUBJ_MAX_FAST if fast_mode else _SUBJ_MAX_FULL
    bmax = _BODY_MAX_FAST if fast_mode else _BODY_MAX_FULL
    s = subject if len(subject) <= smax else subject[:smax] + "…"
    b = body if len(body) <= bmax else body[:bmax] + "\n…[truncated]"
    return s, b


def _compact_context_line(
    user_profile: Optional[Dict[str, Any]],
    company_profile: Optional[Dict[str, Any]],
) -> str:
    parts = []
    if user_profile and user_profile.get("full_name"):
        parts.append(f"Sender: {user_profile.get('full_name')}")
    if company_profile and company_profile.get("company_name"):
        parts.append(f"Company: {company_profile.get('company_name')}")
    return " | ".join(parts) if parts else ""


def _first_balanced_json_object(text: str) -> Optional[str]:
    """Extract first {...} block with balanced braces (avoids greedy-regex failures on trailing text)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_score_only_llm_text(raw: str) -> Dict[str, Any]:
    """
    Parse minimal score-only JSON from the model. Handles markdown fences, optional whitespace,
    truncated outputs (regex fallback for spam_score), and malformed closing.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty score-only response")
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"```\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip()

    blob = _first_balanced_json_object(text)
    if blob:
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            pass

    m = re.search(r'"spam_score"\s*:\s*(\d+)', text)
    if not m:
        m = re.search(r"spam_score\s*:\s*(\d+)", text, re.IGNORECASE)
    if m:
        score = max(0, min(100, int(m.group(1))))
        risk = "Medium"
        m_rl = re.search(r'"risk_level"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
        if m_rl:
            risk = m_rl.group(1)
        return {"spam_score": score, "risk_level": risk, "reasons": []}

    raise ValueError(f"no usable JSON in score-only response: {text[:280]}")


def _normalize_llm_message_content(response) -> str:
    """Gemini/LangChain may return str or list of content blocks."""
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


def _finalize_rewritten_body_html(body: str) -> str:
    """
    Spam LLM often returns HTML <p> blocks; output may truncate mid-paragraph or mangle the closing.
    Repair tag balance and ensure Best regards + [Your Name] so clients get a complete email.
    """
    if not body or not str(body).strip():
        return body
    text = str(body).strip()

    # Truncated company/name junk after "Best regards," (e.g. "...Best regards, What We")
    text = re.sub(
        r"(<p>\s*)Best regards,?\s*What We\b[^<]*",
        r"\1Best regards,</p>\n<p>[Your Name]</p>",
        text,
        flags=re.IGNORECASE,
    )

    open_n = len(re.findall(r"<p\b", text, re.IGNORECASE))
    close_n = text.count("</p>")
    if open_n > close_n:
        last_close = text.rfind("</p>")
        if last_close != -1:
            text = text[: last_close + 4].strip()
        # Drop incomplete trailing <p>… without </p>
        text = re.sub(r"<p>[^<]*$", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"<p>[^<]*Best regards[^<]*$", "", text, flags=re.IGNORECASE).strip()

    lower = text.lower()
    if "best regards" not in lower and "sincerely" not in lower and "kind regards" not in lower:
        text = text.rstrip() + "\n<p>Best regards,</p>\n<p>[Your Name]</p>"
    elif "[your name]" not in lower:
        text = text.rstrip() + "\n<p>[Your Name]</p>"

    return text


def _coerce_spam_analysis_dict(
    data: Dict[str, Any],
    orig_subject: str,
    orig_body: str,
) -> Dict[str, Any]:
    spam_score = int(data.get("spam_score", 0))
    spam_score = max(0, min(100, spam_score))
    risk_level = data.get("risk_level", "Low")
    if risk_level not in ["Low", "Medium", "High", "Draft"]:
        risk_level = "Low"
    reasons = data.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)] if reasons else []
    suggestions = data.get("suggestions", [])
    if not isinstance(suggestions, list):
        suggestions = [str(suggestions)] if suggestions else []
    rs = data.get("rewritten_subject")
    rb = data.get("rewritten_body")
    if not rs or not str(rs).strip():
        rs = orig_subject
    if not rb or not str(rb).strip():
        rb = orig_body
    rb = _finalize_rewritten_body_html(str(rb))
    return {
        "spam_score": spam_score,
        "risk_level": risk_level,
        "reasons": reasons,
        "suggestions": suggestions,
        "rewritten_subject": str(rs),
        "rewritten_body": rb,
    }


def _extract_spam_analysis_from_llm_text(
    text: str,
    orig_subject: str,
    orig_body: str,
) -> Dict[str, Any]:
    """
    Parse spam-check JSON. Handles markdown fences, list-shaped LLM content already flattened,
    complete JSON, and truncated JSON (model hits max tokens mid-stream).
    """
    t = (text or "").strip()
    t = re.sub(r"^```json\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^```\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"```\s*$", "", t, flags=re.IGNORECASE)
    t = t.strip()

    blob = _first_balanced_json_object(t)
    if blob:
        try:
            data = json.loads(blob)
            return _coerce_spam_analysis_dict(data, orig_subject, orig_body)
        except json.JSONDecodeError:
            pass

    m = re.search(r'"spam_score"\s*:\s*(\d+)', t)
    if not m:
        m = re.search(r"spam_score\s*:\s*(\d+)", t, re.IGNORECASE)
    score = max(0, min(100, int(m.group(1)))) if m else 50

    mrl = re.search(r'"risk_level"\s*:\s*"([^"]+)"', t, re.IGNORECASE)
    risk = mrl.group(1) if mrl else "Medium"
    if risk not in ["Low", "Medium", "High", "Draft"]:
        risk = "Medium"

    reasons: list[str] = []
    rm = re.search(r'"reasons"\s*:\s*\[([\s\S]*?)(?:\]|$)', t, re.IGNORECASE)
    if rm:
        chunk = rm.group(1)
        for sm in re.finditer(r'"((?:[^"\\]|\\.)*)"', chunk):
            s = sm.group(1).replace("\\n", "\n").replace('\\"', '"')
            if s.strip():
                reasons.append(s[:800])
            if len(reasons) >= 6:
                break

    suggestions: list[str] = []
    sm = re.search(r'"suggestions"\s*:\s*\[([\s\S]*?)(?:\]|$)', t, re.IGNORECASE)
    if sm:
        chunk = sm.group(1)
        for mg in re.finditer(r'"((?:[^"\\]|\\.)*)"', chunk):
            s = mg.group(1).replace("\\n", "\n").replace('\\"', '"')
            if s.strip():
                suggestions.append(s[:800])
            if len(suggestions) >= 6:
                break

    if not reasons:
        reasons.append(
            "The model response was cut off before the full JSON finished. "
            "Spam score and risk were read from partial data; use your original text or run the check again."
        )

    return {
        "spam_score": score,
        "risk_level": risk,
        "reasons": reasons,
        "suggestions": suggestions,
        "rewritten_subject": orig_subject,
        "rewritten_body": orig_body,
    }


def _get_content_hash(subject: str, body: str) -> str:
    """Generate a hash of the email content for caching, normalizing whitespace."""
    normalized_subject = re.sub(r'\s+', ' ', subject).strip()
    normalized_body = re.sub(r'\s+', ' ', body).strip()
    content = f"{normalized_subject}|{normalized_body}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def _is_low_context_email(subject: str, body: str) -> bool:
    """Check if email lacks meaningful context (e.g., just 'hi' and 'hello')."""
    subject_lower = subject.lower().strip()
    body_lower = body.lower().strip()
    
    # Common low-context patterns
    low_context_patterns = [
        r'^(hi|hello|hey|greetings|good\s+(morning|afternoon|evening))[\s,\.!]*$',
        r'^(hi|hello|hey)[\s,\.!]*$',
    ]
    
    # Check if subject is just a greeting
    is_greeting_only = any(re.match(pattern, subject_lower) for pattern in low_context_patterns)
    
    # Check if body is just a greeting or very short
    is_body_greeting = any(re.match(pattern, body_lower) for pattern in low_context_patterns)
    is_body_very_short = len(body.strip()) < 20
    
    # Total content is very short OR both subject and body are just greetings
    total_length = len(subject) + len(body)
    return total_length < 30 or (is_greeting_only and (is_body_greeting or is_body_very_short))

async def check_email_spam(
    subject: str, 
    body: str, 
    user_profile: Dict[str, Any] = None,
    company_profile: Dict[str, Any] = None,
    fast_mode: bool = False,
    score_only: bool = False,
    user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    subject = subject.strip() if subject else ''
    body = body.strip() if body else ''

    # Check if email lacks context and user/company profile is available
    is_low_context = _is_low_context_email(subject, body)
    has_profile_data = user_profile or company_profile

    # For very short or low-context emails, generate a complete professional template via AI
    if is_low_context and has_profile_data:
        # Build user context from profile data
        user_context_parts = []
        
        if user_profile:
            if user_profile.get('full_name'):
                user_context_parts.append(f"Name: {user_profile.get('full_name')}")
            if user_profile.get('bio'):
                user_context_parts.append(f"About: {user_profile.get('bio')}")
            if user_profile.get('department'):
                user_context_parts.append(f"Department: {user_profile.get('department')}")
            if user_profile.get('location'):
                user_context_parts.append(f"Location: {user_profile.get('location')}")
        
        if company_profile:
            if company_profile.get('company_name'):
                user_context_parts.append(f"Company: {company_profile.get('company_name')}")
            if company_profile.get('company_description'):
                user_context_parts.append(f"Company Description: {company_profile.get('company_description')}")
            if company_profile.get('products_and_services'):
                products = company_profile.get('products_and_services', [])
                if isinstance(products, list) and products:
                    products_str = ', '.join([str(p) for p in products[:5]])  # Limit to first 5
                    user_context_parts.append(f"Products/Services: {products_str}")
        
        user_context = "\n".join(user_context_parts) if user_context_parts else "No additional context available"
        
        # Use AI to generate a complete professional email template using user profile
        template_prompt = f"""You are an expert B2B email copywriter specializing in high-deliverability, spam-free emails. Create a PERFECT, professional outreach email that will NEVER go to spam.

The user has provided minimal input (just a greeting like "hi" or "hello"):
Subject: "{subject}"
Body: "{body}"

Use the following user profile information to create a contextual, professional email:
{user_context}

CRITICAL REQUIREMENTS - This email MUST score < 20 spam score (Low Risk, excellent deliverability):

1. **Subject Line (under 50 characters)**:
   - Meaningful, professional, and specific to what the user does
   - NO spam trigger words (free, urgent, limited time, act now, click here, etc.)
   - NO excessive capitalization or punctuation
   - NO emojis or special characters
   - Reflects the value proposition clearly

2. **Email Structure**:
   - Proper greeting: "Hello {{{{ business_name }}}}," or "Hi {{{{ business_name }}}},"
   - Friendly introduction/rapport line (1-2 sentences)
   - Clear purpose statement - use the user's company/products/services to explain what they do
   - Value proposition based on their business (2-3 sentences)
   - Why it matters to the recipient (1-2 sentences)
   - Clear, soft call to action (not pushy)
   - Professional closing: "Best regards," followed by the sender's actual name (for example, the user's full name). Do not use any bracketed company placeholder like "[Your Company Name]".

3. **Content Quality**:
   - Concise but professional (100-150 words - NOT longer)
   - Professional but conversational tone
   - Natural language - avoid marketing jargon
   - Specific to their business - use company name, products/services, description
   - NO generic templates - make it contextual and relevant

4. **Spam Avoidance**:
   - NO spam trigger words (free, urgent, guarantee, winner, click here, etc.)
   - NO excessive links (maximum 1-2 if needed)
   - NO ALL CAPS or excessive punctuation
   - NO emojis or special characters
   - Proper grammar and spelling
   - Natural sentence structure
   - Balanced text-to-link ratio

5. **Personalization**:
   - Preserve ALL personalization variables EXACTLY in double braces format: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}}
   - CRITICAL: Use DOUBLE BRACES {{{{ }}}} for variables, NOT single braces {{ }}
   - Variables MUST be formatted as: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}} (with spaces inside braces)
   - Use user's actual business context to make it relevant

6. **Professional Standards**:
   - Well-structured with proper paragraphs
   - Clear, concise messaging
   - Professional tone throughout
   - Appropriate for B2B outreach

This email MUST be PERFECT and will score < 20 spam score when checked. It should be ready to send immediately.

Return ONLY valid JSON:
{{
  "rewritten_subject": "Perfect professional subject line (under 50 chars, no spam triggers)",
  "rewritten_body": "Perfect professional email body (100-150 words, low spam risk, well-structured)"
}}

Make it a REAL, COMPLETE, PERFECT email that someone could send immediately with confidence it won't go to spam."""
        
        try:
            template_response = await tracked_ainvoke(
                llm=_spam_check_llm(),
                prompt=template_prompt,
                provider="gemini",
                model=llm_model_name(_spam_check_llm(), fallback=_spam_model),
                feature="spam_rewrite",
                user_id=user_id,
            )
            template_text = getattr(template_response, "content", str(template_response)).strip()
            template_text = re.sub(r'^```json\s*', '', template_text, flags=re.IGNORECASE)
            template_text = re.sub(r'^```\s*', '', template_text, flags=re.IGNORECASE)
            template_text = re.sub(r'```\s*$', '', template_text, flags=re.IGNORECASE)
            
            template_match = re.search(r'\{.*\}', template_text, re.DOTALL)
            if template_match:
                template_result = json.loads(template_match.group(0))
                rewritten_subject = template_result.get('rewritten_subject', 'Professional Outreach Email')
                rewritten_body = template_result.get('rewritten_body', 'Hello {{ business_name }},\n\nI hope this email finds you well.\n\n[Complete professional email content here]\n\nBest regards,\n[Your Name]')
            else:
                rewritten_subject = 'Professional Outreach Email'
                rewritten_body = 'Hello {{ business_name }},\n\nI hope this email finds you well.\n\n[Complete professional email content here]\n\nBest regards,\n[Your Name]'
        except Exception:
            # Fallback template
            rewritten_subject = 'Professional Outreach Email'
            rewritten_body = 'Hello {{ business_name }},\n\nI hope this email finds you well.\n\n[Complete professional email content here]\n\nBest regards,\n[Your Name]'
        
        return {
            "spam_score": 95,  # High spam score for original too-short email
            "risk_level": "High",
            "reasons": ["Draft too short to evaluate", "Email lacks professional structure and content"],
            "suggestions": [
                "Use the AI-improved version below - it's optimized for low spam risk (< 20 score)",
                "The rewritten version follows best practices for email deliverability",
                "Includes proper structure, avoids spam triggers, and is professionally written"
            ],
            "rewritten_subject": rewritten_subject,
            "rewritten_body": rewritten_body  # This rewritten version is optimized for < 20 spam score
        }

    content_hash = _get_content_hash(subject, body)
    score_cache_key = f"{content_hash}:score:{'fast' if fast_mode else 'full'}"

    # Backend-only: score the draft without asking the model for full rewrites (much faster).
    if score_only:
        if score_cache_key in _spam_check_cache:
            return _spam_check_cache[score_cache_key]
        subject_llm, body_llm = _truncate_for_spam_llm(subject, body, fast_mode)
        compact_line = _compact_context_line(user_profile, company_profile)
        ctx_prefix = f"Context: {compact_line}\n" if compact_line else ""
        prompt = f"""Return ONLY one JSON object on one line. No markdown, no other text.
Keys exactly: "spam_score" (integer 0-100, 0=best inbox) and "risk_level" ("Low" or "Medium" or "High").
Example: {{"spam_score":25,"risk_level":"Low"}}
Calibration: normal short B2B outreach with placeholders (no FREE/URGENT/ALL CAPS/excessive links) is usually spam_score 10-40 (inbox safety 60-90%). Reserve spam_score 65+ for obvious spam, empty/gibberish, or severe merged-word typos (e.g. "Ifantastic"). Minor grammar may be ignored; broken or nonsense sentences should score higher.
{ctx_prefix}Subject: {subject_llm}
Body: {body_llm}
"""
        try:
            response = await tracked_ainvoke(
                llm=_spam_score_only_llm(),
                prompt=prompt,
                provider="gemini",
                model=llm_model_name(_spam_score_only_llm(), fallback=_spam_model),
                feature="spam_score",
                user_id=user_id,
            )
            text = getattr(response, "content", str(response)).strip()
            if not text:
                raise HTTPException(status_code=500, detail="Empty response from Gemini API")
            try:
                result = _parse_score_only_llm_text(text)
            except ValueError as ve:
                logger.warning("Spam score parse failed: %s", ve)
                raise HTTPException(
                    status_code=500,
                    detail="Spam check failed. Please try again.",
                )
            spam_score = int(result.get("spam_score", 0))
            spam_score = max(0, min(100, spam_score))
            risk_level = result.get("risk_level", "Low")
            if risk_level not in ["Low", "Medium", "High", "Draft"]:
                risk_level = "Low"
            reasons = result.get("reasons", [])
            if not isinstance(reasons, list):
                reasons = [str(reasons)] if reasons else []
            final_result = {
                "spam_score": spam_score,
                "risk_level": risk_level,
                "reasons": reasons,
                "suggestions": [],
                "rewritten_subject": subject,
                "rewritten_body": body,
                "rewritten_spam_score": None,
                "rewritten_risk_level": "Low",
            }
            _spam_check_cache[score_cache_key] = final_result
            return final_result
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail="Spam check failed. Please try again.")

    if content_hash in _spam_check_cache:
        return _spam_check_cache[content_hash]

    # Build user context for the prompt if available
    user_context_section = ""
    if user_profile or company_profile:
        context_parts = []
        if user_profile:
            if user_profile.get('full_name'):
                context_parts.append(f"Sender Name: {user_profile.get('full_name')}")
            if user_profile.get('bio'):
                context_parts.append(f"About Sender: {user_profile.get('bio')}")
            if user_profile.get('department'):
                context_parts.append(f"Department: {user_profile.get('department')}")
        if company_profile:
            if company_profile.get('company_name'):
                context_parts.append(f"Company: {company_profile.get('company_name')}")
            if company_profile.get('company_description'):
                context_parts.append(f"Company Description: {company_profile.get('company_description')}")
            if company_profile.get('products_and_services'):
                products = company_profile.get('products_and_services', [])
                if isinstance(products, list) and products:
                    products_str = ', '.join([str(p) for p in products[:5]])
                    context_parts.append(f"Products/Services: {products_str}")
        
        if context_parts:
            user_context_section = f"\n\nUser Context (use this to make the rewritten email more contextual and relevant):\n" + "\n".join(context_parts)

    subject_llm, body_llm = _truncate_for_spam_llm(subject, body, fast_mode)
    compact_line = _compact_context_line(user_profile, company_profile)

    if fast_mode:
        # Minimal prompt + Flash model + truncation + output cap = lowest latency path.
        ctx_prefix = f"Context: {compact_line}\n" if compact_line else ""
        prompt = f"""Return ONLY valid JSON. No markdown. One object. Keep strings concise so the JSON completes.
Schema:
{{"spam_score":0-100,"risk_level":"Low"|"Medium"|"High","reasons":["≤3 short items"],"suggestions":["≤3 short items"],"rewritten_subject":"≤72 chars, professional, no spam triggers","rewritten_body":"HTML <p>...</p> B2B body, ≤130 words. Greeting Hello {{{{ business_name }}}}, or Hi {{{{ business_name }}}},. Keep {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}} if present. No spam phrases. Best regards then [Your Name]."}}

spam_score 0=best. Raise score for spam triggers, ALL CAPS, no structure, too short, draft quality.
{ctx_prefix}
Subject: {subject_llm}
Body: {body_llm}
"""
    else:
        prompt = f"""You are an email deliverability, spam analyzer, and professional email quality evaluator.
    Return ONLY valid JSON. No markdown. No explanations.
    Format:
    {{
      "spam_score": 0-100,
      "risk_level": "Low|Medium|High",
      "reasons": ["..."],
      "suggestions": ["..."],
      "rewritten_subject": "A revised version of the subject line that avoids spam triggers and improves deliverability",
      "rewritten_body": "A revised version of the email body that improves deliverability while keeping the original intent and maintaining all personalization variables (preserve {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}}, etc.)"
    }}
    
    Analyze this email for BOTH spam risk AND professional quality. An email must be professional and well-written to pass.
    {user_context_section}
    
    Evaluate:
    1. **Spam Score (0-100, where 0 is best)**: Consider spam triggers, but ALSO consider:
       - Is the email too short or lacks substance? (Add 30-50 points)
       - Does it lack professional structure (greeting, body, closing)? (Add 20-40 points)
       - Is the subject line meaningful and professional? (Add 10-30 points if not)
       - Does it look unprofessional or like a draft? (Add 20-40 points)
       - Are there spam trigger words? (Add 10-30 points)
    
    2. **Risk Level**: 
       - Low: score < 30 AND email is professional, well-structured, and meaningful
       - Medium: score 30-79 OR email lacks professionalism/structure
       - High: score >= 80 OR email is clearly unprofessional/incomplete
    
    3. **Reasons**: List why it might be marked as spam OR why it's unprofessional
    
    4. **Suggestions**: Provide actionable suggestions to improve professionalism AND deliverability
    
    5. **Rewritten Version**: Create a PERFECT, professional, well-structured email that will score < 20 spam score (Low Risk). This is CRITICAL - the rewritten version MUST be optimized for maximum deliverability:
       
       **MANDATORY STRUCTURE:**
       - Proper greeting: "Hello {{{{ business_name }}}}," or "Hi {{{{ business_name }}}},"
       - Friendly introduction/rapport line (1-2 sentences)
       - Clear purpose statement that preserves the original email's topic/intent
       - Supporting detail (2-3 sentences) that advances that same topic — do not invent a new product pitch
       - Why it matters to recipient (1-2 sentences)
       - Soft, clear call to action (not pushy)
       - Professional closing: "Best regards," then on the next line EXACTLY "[Your Name]". This is a placeholder for the USER to fill in—NEVER substitute with any other name like "Alex M." or "John Doe".
       - CRITICAL: Use [Your Name] consistently for the sender (e.g. "My name is [Your Name] and I...")—NEVER use "[Name]". Do not introduce any bracketed company-name placeholder such as "[Your Company Name]"; instead, when needed, refer to the company naturally using the profile/company context.
       
       **MANDATORY SPAM AVOIDANCE (CRITICAL):**
       - NO spam trigger words: free, urgent, guarantee, winner, click here, act now, limited time, etc.
       - NO excessive capitalization or punctuation
       - NO emojis or special characters
       - NO excessive links (maximum 1-2 if needed)
       - Natural, conversational language (avoid marketing jargon)
       - Proper grammar and spelling
       - Balanced text-to-link ratio
       
       **MANDATORY QUALITY STANDARDS:**
       - Concise but complete (100-150 words ideal, up to 200 if original was very short)
       - Professional but conversational tone
       - Well-structured with proper paragraphs
       - Preserves ALL personalization variables EXACTLY in double braces format: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}}
       - CRITICAL: Use DOUBLE BRACES {{{{ }}}} for variables, NOT single braces {{ }}
       - Variables MUST be formatted as: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}} (with spaces inside braces)
       - Meaningful subject line under 50 characters (NO spam triggers)
       - If user context is provided, use it to make the email contextual and relevant
       
       **CRITICAL REQUIREMENT:** The rewritten version MUST score < 20 spam score when checked. It should be PERFECT and ready to send immediately. Prioritize deliverability over length - a concise, well-written email is better than a long one.
    
    CRITICAL: The rewritten version MUST be PERFECT, PROFESSIONAL, and optimized for LOW SPAM RISK (< 20 score). 
    Quality over quantity - ensure it's well-written, spam-free, and professional rather than unnecessarily long.
    The rewritten version should be ready to send immediately with confidence it won't go to spam.
    
    IMPORTANT: 
    - If the email is too short, unprofessional, or lacks structure, assign a HIGH spam score (70-95) and provide a COMPLETE professional rewrite that implements ALL suggestions.
    - CRITICAL TOPIC FIDELITY: The rewrite MUST keep the original email's topic, ask, and intent. Do NOT replace it with a generic product pitch or company value-prop from the profile.
    - If user/company context is provided, use it only for sender identity (name, company) — never change what the email is about.
    - Keep rewritten emails concise (100-150 words) unless the original email was very short - don't make them unnecessarily long.
    
    Subject: {subject_llm}
    Body: {body_llm}
    """

    try:
        response = await tracked_ainvoke(
            llm=_spam_check_llm(),
            prompt=prompt,
            provider="gemini",
            model=llm_model_name(_spam_check_llm(), fallback=_spam_model),
            feature="spam_score",
            user_id=user_id,
        )
        text = _normalize_llm_message_content(response)

        if not text:
            raise HTTPException(status_code=500, detail="Empty response from Gemini API")

        parsed = _extract_spam_analysis_from_llm_text(text, subject, body)
        spam_score = parsed["spam_score"]
        risk_level = parsed["risk_level"]
        reasons = parsed["reasons"]
        suggestions = parsed["suggestions"]
        rewritten_subject = parsed["rewritten_subject"]
        rewritten_body = parsed["rewritten_body"]
        # Normalize placeholders: [Name] -> [Your Name]
        rewritten_body = re.sub(r'\[Name\]', '[Your Name]', rewritten_body, flags=re.IGNORECASE)

        # In fast_mode, skip validation and regeneration for speed
        if fast_mode:
            final_result = {
                "spam_score": spam_score,
                "risk_level": risk_level,
                "reasons": reasons,
                "suggestions": suggestions,
                "rewritten_subject": rewritten_subject,
                "rewritten_body": rewritten_body,
                "rewritten_spam_score": None,
                "rewritten_risk_level": "Low",
            }
        else:
            rewritten_score = await _validate_rewritten_content(
                rewritten_subject, rewritten_body, user_profile, company_profile, user_id=user_id
            )

            max_retries = 3
            retry_count = 0
            while rewritten_score >= 20 and retry_count < max_retries:
                retry_count += 1
                regenerated = await _regenerate_low_risk_email(
                    rewritten_subject,
                    rewritten_body,
                    rewritten_score,
                    user_profile,
                    company_profile,
                    user_id=user_id,
                )
                rewritten_subject = regenerated["subject"]
                rewritten_body = regenerated["body"]
                rewritten_score = regenerated["score"]

            if rewritten_score < 20:
                final_result = {
                    "spam_score": spam_score,
                    "risk_level": risk_level,
                    "reasons": reasons,
                    "suggestions": suggestions,
                    "rewritten_subject": rewritten_subject,
                    "rewritten_body": rewritten_body,
                    "rewritten_spam_score": rewritten_score,
                    "rewritten_risk_level": "Low",
                }
            else:
                final_result = {
                    "spam_score": spam_score,
                    "risk_level": risk_level,
                    "reasons": reasons,
                    "suggestions": suggestions,
                    "rewritten_subject": rewritten_subject,
                    "rewritten_body": rewritten_body,
                    "rewritten_spam_score": rewritten_score,
                    "rewritten_risk_level": "Low",
                }

        _spam_check_cache[content_hash] = final_result
        return final_result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Spam check failed. Please try again.")


async def _validate_rewritten_content(
    subject: str, 
    body: str, 
    user_profile: Dict[str, Any] = None,
    company_profile: Dict[str, Any] = None,
    user_id: Optional[Any] = None,
) -> int:
    """Quickly validate rewritten content spam score. Returns spam score (0-100)."""
    validation_prompt = f"""You are an expert email deliverability analyzer. Analyze this email and return ONLY a spam score from 0-100.

Email Subject: {subject}
Email Body: {body}

Return ONLY a JSON object with a single field "spam_score" (integer 0-100).
Lower scores (0-19) = Low risk, excellent deliverability
Medium scores (20-79) = Medium risk
High scores (80-100) = High spam risk

{{"spam_score": <number>}}
"""
    
    try:
        response = await tracked_ainvoke(
            llm=_spam_check_llm(),
            prompt=validation_prompt,
            provider="gemini",
            model=llm_model_name(_spam_check_llm(), fallback=_spam_model),
            feature="spam_score",
            user_id=user_id,
        )
        text = getattr(response, "content", str(response)).strip()
        text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^```\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'```\s*$', '', text, flags=re.IGNORECASE)
        
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            score = int(result.get('spam_score', 50))
            return max(0, min(100, score))
        return 50  # Default to medium if parsing fails
    except Exception:
        return 50  # Default to medium if validation fails


async def _regenerate_low_risk_email(
    current_subject: str,
    current_body: str,
    current_score: int,
    user_profile: Dict[str, Any] = None,
    company_profile: Dict[str, Any] = None,
    user_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Regenerate email with stricter instructions to ensure < 20 spam score."""
    
    # Build user context if available
    user_context_section = ""
    if user_profile or company_profile:
        context_parts = []
        if user_profile:
            if user_profile.get('full_name'):
                context_parts.append(f"Sender Name: {user_profile.get('full_name')}")
            if user_profile.get('bio'):
                context_parts.append(f"About Sender: {user_profile.get('bio')}")
            if user_profile.get('department'):
                context_parts.append(f"Department: {user_profile.get('department')}")
        if company_profile:
            if company_profile.get('company_name'):
                context_parts.append(f"Company: {company_profile.get('company_name')}")
            if company_profile.get('company_description'):
                context_parts.append(f"Company Description: {company_profile.get('company_description')}")
            if company_profile.get('products_and_services'):
                products = company_profile.get('products_and_services', [])
                if isinstance(products, list) and products:
                    products_str = ', '.join([str(p) for p in products[:5]])
                    context_parts.append(f"Products/Services: {products_str}")
        
        if context_parts:
            user_context_section = "\n\nUSER CONTEXT (use this to make the email relevant):\n" + "\n".join(context_parts)
    
    strict_prompt = f"""You are an expert B2B email copywriter. The previous version scored {current_score}/100 (too high). 

CRITICAL: Generate a PERFECT email that will score < 15 spam score (NOT 20, but < 15 for extra safety).

Current version (score: {current_score}/100):
Subject: {current_subject}
Body: {current_body}
{user_context_section}

STRICT REQUIREMENTS FOR < 15 SPAM SCORE:
1. Subject: Under 45 characters, NO spam words, professional, specific
2. Body: 100-130 words MAX (shorter = better deliverability)
3. NO spam triggers: free, urgent, guarantee, winner, click, act now, limited time, etc.
4. NO excessive punctuation, capitalization, or emojis
5. Natural, conversational language (avoid marketing jargon)
6. Maximum 1 link if absolutely necessary
7. Proper structure: greeting, value prop, soft CTA, professional closing
8. Use double braces for variables: {{{{ business_name }}}}, {{{{ industry }}}}, {{{{ address }}}}
9. Use [Your Name] only for the sender’s name (e.g. "My name is [Your Name] and I…")—never [Name] or a made-up sample name.

Return ONLY JSON:
{{
  "subject": "Perfect subject (< 45 chars, < 15 spam score)",
  "body": "Perfect email body (100-130 words, < 15 spam score, professional)"
}}
"""
    
    try:
        response = await tracked_ainvoke(
            llm=_spam_check_llm(),
            prompt=strict_prompt,
            provider="gemini",
            model=llm_model_name(_spam_check_llm(), fallback=_spam_model),
            feature="spam_rewrite",
            user_id=user_id,
        )
        text = getattr(response, "content", str(response)).strip()
        text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'^```\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'```\s*$', '', text, flags=re.IGNORECASE)
        
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            new_subject = result.get('subject', current_subject)
            new_body = result.get('body', current_body)
            # Same placeholder normalization as main flow
            new_body = re.sub(r'\[Name\]', '[Your Name]', new_body, flags=re.IGNORECASE)
            # Validate the new version
            new_score = await _validate_rewritten_content(new_subject, new_body, user_profile, company_profile, user_id=user_id)
            
            return {
                'subject': new_subject,
                'body': new_body,
                'score': new_score
            }
    except Exception:
        pass
    
    # Fallback: return current version
    return {
        'subject': current_subject,
        'body': current_body,
        'score': current_score
    }

