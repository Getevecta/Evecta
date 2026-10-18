import json
import re
from typing import Dict, Any, List, Optional, Union
from uuid import UUID
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage
from app.services.llm import get_llm, get_lead_context_llm
from app.services.ai.tracked_llm import tracked_ainvoke, tracked_invoke, llm_model_name
from app.core.config import get_settings


DEFAULT_PATHS = [
    "", "about", "about-us", "company", "services",
    "products", "solutions", "what-we-do", "who-we-are",
    "contact", "contact-us"
]
ALLOWED_EMAIL_PREFIXES = [
    "info", "contact", "support", "sales", "hello",
    "service", "team"
]

EMAIL_REGEX = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"


# SCRAPING
def fetch_url(url: str) -> str:
    from app.utils.safe_http import safe_http_get_text

    try:
        return safe_http_get_text(url) or ""
    except Exception:
        return ""


def clean_html(html: str) -> str:
    """Remove scripts/styles but keep main readable content."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    for tag in ["script", "style", "noscript"]:
        for t in soup.find_all(tag):
            t.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def scrape_website_text(base_url: str, max_chars: int = 12000) -> str:
    """Scrape common top-level URLs."""
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    collected: List[str] = []

    for path in DEFAULT_PATHS:
        full_url = urljoin(base_url.rstrip("/") + "/", path)
        html = fetch_url(full_url)
        if not html:
            continue

        text = clean_html(html)
        if text:
            collected.append(text)

        if len("\n\n".join(collected)) >= max_chars:
            break

    return "\n\n".join(collected)[:max_chars]

def extract_business_email(text: str) -> str | None:
    """Extract business email using allowed prefixes only."""
    import re

    matches = re.findall(EMAIL_REGEX, text, flags=re.IGNORECASE)
    if not matches:
        return None

    # Check prefix rules
    for email in matches:
        prefix = email.split("@")[0].lower()

        for allowed in ALLOWED_EMAIL_PREFIXES:
            if prefix.startswith(allowed):
                return email  # first valid match

    return None

# JSON FIXER
def safe_json_loads(raw: str) -> Dict[str, Any]:
    """Extract valid JSON even if wrapped in text or code blocks."""
    try:
        return json.loads(raw)
    except Exception:
        cleaned = re.sub(r"```json|```", "", raw).strip()

        match = re.search(r"{.*}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

    return {}


# GEMINI EXTRACTION
def extract_company_profile(
    url: str,
    text: str,
    user_id: Optional[Union[str, UUID]] = None,
) -> Dict[str, Any]:
    if len(text) < 300:
        return {}

    llm = get_llm()
    settings = get_settings()

    prompt = f"""
Return ONLY valid JSON. No explanation. No markdown.

Extract these fields from the website content:

{{
  "industry": string or null,
  "company_description": string or null,
  "products_and_services": [{{"name": string, "description": string}}] or [],
  "business_offers": [string] or [],
  "unique_selling_points": [string] or [],
  "customer_goals": [string] or [],
  "problems_solved": [string] or [],
  "benefits": [string] or [],
  "achievements": [string] or [],
  "business_email": string or null,
  "primary_address": {{
      "country": string or null,
      "state": string or null,
      "city": string or null,
      "postal_code": string or null
  }}
}}

RULES:
- Return ONLY PURE JSON (no Markdown, no commentary).
- Do NOT invent information. Use null or [] if missing.
- business_email MUST be a company-domain email (no gmail, outlook, yahoo, hotmail, protonmail).
- If only personal emails are found → set business_email = null.
- Group products into **3–6 high-level categories**, not long lists of items.
- Product descriptions must be **short**, max **12–15 words**.
- Business email must be company-domain only.
Website: {url}

Content:
{text}
"""

    response = tracked_invoke(
        llm=llm,
        prompt=[HumanMessage(content=prompt)],
        provider="gemini",
        model=llm_model_name(llm, fallback=settings.GEMINI_MODEL),
        feature="company_profile",
        user_id=user_id,
    )
    raw = response.content.strip()

    return safe_json_loads(raw)


# MAP TO DB FIELDS
def map_to_company_update(data: dict) -> Dict[str, Any]:
    if not data:
        return {}

    addr = data.get("primary_address", {}) or {}
    industry = data.get("industry")
    if isinstance(industry, list):
        industry = ", ".join(industry)
 
    return {
        "industry": industry,
        "company_description": data.get("company_description"),
        "products_and_services": data.get("products_and_services"),
        "business_offers": data.get("business_offers"),
        "unique_selling_point": data.get("unique_selling_points"),
        "customer_goals": data.get("customer_goals"),
        "problems_solved": data.get("problems_solved"),
        "benefits": data.get("benefits"),
        "achievements": data.get("achievements"),
        "email": data.get("business_email"),
        "country": addr.get("country"),
        "state": addr.get("state"),
        "city": addr.get("city"),
        "postal_code": addr.get("postal_code"),
    }


# UPDATED MAIN ENTRY
def run_company_scraper_sync(
    website_url: str,
    text: str,
    user_id: Optional[Union[str, UUID]] = None,
) -> Dict[str, Any]:
    extracted = extract_company_profile(website_url, text, user_id=user_id)
    mapped = map_to_company_update(extracted)

    email = extract_business_email(text)
    if email:
        mapped["business_email"] = email

    return mapped


# ── LEAD CONTEXT EXTRACTION ──────────────────────────────────────────────────
# Lighter, lead-focused extraction used during enrichment. Unlike the company
# scraper above (which fills the *user's own* Company profile), this returns just
# the three personalization fields stored on a lead row. `services` is returned
# as comma-joined text so it drops straight into email merge fields.

def _flatten_services(value: Any) -> str | None:
    """Normalize the LLM `services` field (list of strings or {name: ...} dicts) to comma-joined text."""
    if not value:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None

    names: List[str] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                name = item.strip()
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
            else:
                name = str(item).strip()
            if name:
                names.append(name)

    # De-dup while preserving order, cap at 6 to keep merge text tidy.
    seen: set[str] = set()
    unique = []
    for n in names:
        key = n.lower()
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return ", ".join(unique[:6]) or None


LEAD_CONTEXT_MAX_CHARS = 6000
_EMPTY_LEAD_CONTEXT = {"services": None, "website_summary": None, "business_description": None}


def build_context_text(texts: list[str], max_chars: int = LEAD_CONTEXT_MAX_CHARS) -> str:
    """Clean + join already-fetched raw HTML pages into context text for the LLM.

    The pages are fetched once by the enrichment path (shared with email-finding); this
    just turns that raw HTML into capped, cleaned text.
    """
    cleaned = [clean_html(t) for t in texts]
    return "\n\n".join(c for c in cleaned if c)[:max_chars]


def _build_lead_context_prompt(url: str, text: str) -> str:
    return f"""
Return ONLY valid JSON. No explanation. No markdown.

Extract these fields about THIS business from its website content:

{{
  "website_summary": string or null,
  "services": [string] or [],
  "business_description": string or null
}}

RULES:
- Return ONLY PURE JSON (no Markdown, no commentary).
- Do NOT invent information. Use null or [] if missing.
- website_summary: ONE or TWO sentences summarizing what the business does (max ~40 words).
- business_description: ONE or TWO sentences describing the business/its focus (max ~40 words).
- services: 3-6 short service/offering names (each max ~5 words). NOT long sentences.
Website: {url}

Content:
{text}
"""


def _shape_lead_context(data: Dict[str, Any]) -> Dict[str, Any]:
    if not data:
        return dict(_EMPTY_LEAD_CONTEXT)

    def _clean_str(v: Any) -> str | None:
        if not v:
            return None
        s = str(v).strip()
        return s or None

    return {
        "services": _flatten_services(data.get("services")),
        "website_summary": _clean_str(data.get("website_summary")),
        "business_description": _clean_str(data.get("business_description")),
    }


async def extract_lead_context(
    url: str,
    text: str,
    user_id: Optional[Union[str, UUID]] = None,
) -> Dict[str, Any]:
    """
    Extract the three personalization fields from scraped text (async, Flash model).

    Returns {"services", "website_summary", "business_description"} — any field may be
    None. Never invents data; returns all-None when there is too little text.
    """
    if not text or len(text) < 300:
        return dict(_EMPTY_LEAD_CONTEXT)

    llm = get_lead_context_llm()
    settings = get_settings()
    prompt = _build_lead_context_prompt(url, text)

    try:
        response = await tracked_ainvoke(
            llm=llm,
            prompt=[HumanMessage(content=prompt)],
            provider="gemini",
            model=llm_model_name(llm, fallback=settings.GEMINI_MODEL or "gemini-2.5-flash"),
            feature="lead_context",
            user_id=user_id,
        )
        raw = (response.content or "").strip()
        data = safe_json_loads(raw)
    except Exception:
        return dict(_EMPTY_LEAD_CONTEXT)

    return _shape_lead_context(data)
