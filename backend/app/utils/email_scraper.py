import asyncio
import logging
import time

logger = logging.getLogger(__name__)
from app.utils.chat_helper import (
    clean_domain,
    compute_score,
)
import httpx
import re
from typing import Optional
from app.core.config import get_settings
from app.services.external_api_usage import record_hunter_usage
from app.utils.safe_http import async_safe_http_get_text

HUNTER_API_KEY = get_settings().HUNTER_API_KEY
HTTP_TIMEOUT = 10.0

# ✓ FIXED: Updated ALLOWED_PREFIXES with hotel-specific prefixes
ALLOWED_PREFIXES = [
    "info", "contact", "hello", "support", "sales", "admin",
    "office", "team", "enquiries", "marketing",
]

# ✓ Common business email domains (accept with business prefixes)
BUSINESS_DOMAINS = {
    "gmail.com", "outlook.com", "hotmail.com", "yahoo.com",
    "aol.com", "mail.com", "protonmail.com", "icloud.com",
}

FAST_PATHS = ["/", "/contact", "/contact-us"]

# ✓ Expanded paths for better coverage
EXPANDED_PATHS = [
    "/", "/contact", "/contact-us",
]

# Union of contact paths (emails) + about/services paths (context). Fetched ONCE per
# lead during enrichment so email-finding and context extraction share one crawl.
ENRICH_FETCH_PATHS = [
    "/", "/contact", "/contact-us", "/about", "/about-us", "/services",
]

# ✓ FIXED: Better email regex (stricter, more accurate)
EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,}\b'
HUNTER_COMPANY_FIND_URL = "https://api.hunter.io/v2/companies/find"


class HunterRateLimited(Exception):
    """Hunter.io returned HTTP 429 after retries — not the same as 'no email'."""


def _retry_after_seconds(resp: httpx.Response) -> float:
    raw = resp.headers.get("Retry-After", "")
    try:
        delay = float(raw)
    except ValueError:
        return 1.0
    return min(max(delay, 1.0), 30.0)


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _extract_local_domain(email: str) -> tuple[Optional[str], Optional[str]]:
    email = _normalize(email)
    if "@" not in email:
        return None, None
    local, dom = email.split("@", 1)
    local, dom = local.strip(), dom.strip()
    if not local or not dom:
        return None, None
    return local, dom


def _is_company_domain_email(email_domain: str, company_domain: str) -> bool:
    return email_domain == company_domain or email_domain.endswith("." + company_domain)


def _pick_best_email(email_addresses: list[str], domain: str) -> Optional[str]:
    """
    Pick ONLY ONE email:
    1) keep only emails belonging to the domain / subdomain
    2) prefer allowed prefixes in the exact order of ALLOWED_PREFIXES
    3) if no prefix match, return the first domain email
    """
    domain = _normalize(domain)
    if not domain or not email_addresses:
        return None

    # Filter company domain emails + dedupe (preserve order)
    filtered = []
    seen = set()
    for raw in email_addresses:
        email = _normalize(raw)
        if not email or email in seen:
            continue

        local, email_domain = _extract_local_domain(email)
        if local is None:
            continue

        if not _is_company_domain_email(email_domain, domain):
            continue

        seen.add(email)
        filtered.append(email)

    if not filtered:
        return None

    # Rank by prefix priority
    prefix_rank = {p: i for i, p in enumerate(ALLOWED_PREFIXES)}

    def rank_key(email: str) -> tuple[int, int]:
        local, _ = _extract_local_domain(email)
        local = local or ""

        # Exact prefix match: "info@domain.com"
        if local in prefix_rank:
            return (0, prefix_rank[local])

        # Weak match: "info-us@", "support_team@", etc.
        for p, idx in prefix_rank.items():
            if local.startswith(p):
                return (1, idx)

        return (2, 9999)

    filtered.sort(key=rank_key)
    return filtered[0]


# HUNTER.io FALLBACK (COMPANY ENRICHMENT)
async def hunter_fallback_company(domain: str, semaphores) -> list[dict]:
    """
    Uses Hunter Company Enrichment (/v2/companies/find) and returns only 1 email.
    NOTE: This endpoint expects 'domain', not 'business_name'.
    """
    if not HUNTER_API_KEY:
        return []

    domain = _normalize(domain)
    if not domain:
        return []

    params = {
        "domain": domain,
        "api_key": HUNTER_API_KEY,
    }

    async with semaphores.hunter:
        started = time.perf_counter()
        http_status: Optional[int] = None
        try:
            resp = None
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                for attempt in range(3):
                    resp = await client.get(HUNTER_COMPANY_FIND_URL, params=params)
                    http_status = resp.status_code
                    if resp.status_code != 429:
                        break
                    delay = _retry_after_seconds(resp)
                    logger.warning(
                        "[Hunter] 429 rate limited for %s (attempt %s/3, sleep %.1ss)",
                        domain,
                        attempt + 1,
                        delay,
                    )
                    if attempt < 2:
                        await asyncio.sleep(delay)

            if resp is None:
                return []

            if resp.status_code == 429:
                logger.warning("[Hunter] still rate limited for %s after retries", domain)
                raise HunterRateLimited()

            if resp.status_code != 200:
                logger.info("[Hunter] company api returned %s", resp.status_code)
                return []

            payload = resp.json() or {}
            data = payload.get("data") or {}
            site = data.get("site") or {}
            email_addresses = site.get("emailAddresses") or []

            if not isinstance(email_addresses, list):
                return []

            best_email = _pick_best_email(email_addresses, domain)
            if not best_email:
                return []

            local, _ = _extract_local_domain(best_email)
            prefix_ok = any((local or "").startswith(p) for p in ALLOWED_PREFIXES)

            return [{
                "email": best_email,
                "mx_ok": True,
                "smtp_ok": False,
                "score": compute_score(True, prefix_ok),
                "source": "hunter_company_enrichment",
                "hunter_data": data,
            }]

        except HunterRateLimited:
            raise
        except Exception as e:
            logger.error(f"[Hunter] Company enrichment failed for {domain}: {e}")
            return []
        finally:
            await record_hunter_usage(
                api_name="company_find",
                http_status=http_status,
                latency_ms=int((time.perf_counter() - started) * 1000),
                feature="email_enrichment",
                meta=domain,
            )


# SHARED FETCH + EXTRACT HELPERS
# These let the enrichment path fetch a lead's site ONCE and feed the same page text
# to both email-finding and context extraction (see lead_generation_service.enrich_lead).
async def fetch_pages_raw(domain: str, paths: list[str], semaphores) -> list[str]:
    """Fetch raw HTML for the given paths concurrently. Returns 200-body texts only.

    Tries https first and only falls back to http if https yields nothing — this avoids
    fetching every page twice (the old http+https approach double-fetched, since http
    usually just 301-redirects to the same https URL).
    """
    domain = clean_domain(domain)

    async def fetch_one(url: str) -> str | None:
        async with semaphores.http:
            try:
                return await async_safe_http_get_text(url, timeout=HTTP_TIMEOUT)
            except Exception:
                return None

    async def fetch_path(path: str) -> str | None:
        text = await fetch_one(f"https://{domain}{path}")
        if text is None:
            text = await fetch_one(f"http://{domain}{path}")
        return text

    responses = await asyncio.gather(*[fetch_path(p) for p in paths])
    return [r for r in responses if r]


def emails_from_texts(texts: list[str], domain: str, mx_ok: bool) -> list[dict]:
    """Regex-extract + filter company/business emails from already-fetched page texts."""
    results: list[dict] = []
    seen: set[str] = set()
    for text in texts:
        for email in re.findall(EMAIL_REGEX, text):
            email = email.lower().strip()
            if email in seen:
                continue
            seen.add(email)

            try:
                local, email_domain = email.split("@", 1)
            except ValueError:
                continue

            is_company_domain = email_domain == domain or email_domain.endswith("." + domain)
            prefix_ok = any(local.startswith(p) for p in ALLOWED_PREFIXES)
            domain_in_email = domain.replace(".", "").lower() in local.lower()
            is_business_email = (prefix_ok or domain_in_email) and email_domain in BUSINESS_DOMAINS

            # Only accept company emails OR business emails (no pure personal emails)
            if not (is_company_domain or is_business_email):
                continue

            results.append({
                "email": email,
                "mx_ok": mx_ok,
                "score": compute_score(mx_ok, prefix_ok),
                "smtp_ok": False,
                "source": "static",
            })
    return results


def pick_best_result(items: list[dict]) -> list[dict]:
    """Return ONLY ONE email result using prefix priority, else highest score."""
    if not items:
        return []
    for prefix in ALLOWED_PREFIXES:
        for r in items:
            if r.get("email", "").lower().startswith(prefix + "@"):
                return [r]
    return [max(items, key=lambda x: x.get("score", 0))]