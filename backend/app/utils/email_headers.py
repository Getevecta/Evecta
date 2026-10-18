from email.message import Message
from urllib.parse import quote, urlparse

from app.core.config import get_settings


def _unsubscribe_mailto_address(lead_id: str, email: str) -> str | None:
    """Optional mailto fallback for List-Unsubscribe (RFC 2369)."""
    try:
        host = urlparse(get_settings().EMAIL_TRACKING_BASE_URL).hostname
        if not host or host in ("localhost", "127.0.0.1"):
            return None
        subject = quote(f"unsubscribe:{lead_id}:{email}")
        return f"unsubscribe@{host}?subject={subject}"
    except Exception:
        return None


def build_list_unsubscribe_header_value(
    unsubscribe_url: str,
    *,
    lead_id: str | None = None,
    lead_email: str | None = None,
) -> str:
    """Return the List-Unsubscribe header value (HTTPS URI only).

    Gmail's native unsubscribe UI requires a single HTTPS URL (RFC 8058).
    A mailto fallback can prevent Gmail from showing the header link on SES mail.
    """
    return f"<{unsubscribe_url}>"


def apply_list_unsubscribe_headers(
    msg: Message,
    unsubscribe_url: str | None,
    campaign_id: str | None = None,
    lead_id: str | None = None,
    lead_email: str | None = None,
) -> None:
    """
    Add RFC 8058 headers so Gmail/Outlook show native Unsubscribe in the
    message header and inbox row hover actions.

    unsubscribe_url must be the HTTPS one-click endpoint (POST unsubscribes immediately).

  Note: Gmail only shows native UI when DKIM covers List-Unsubscribe and
    List-Unsubscribe-Post (works best with SYSTEM/SES domain sending).
    """
    if not unsubscribe_url:
        return

    parsed = urlparse(unsubscribe_url)
    is_https = parsed.scheme == "https"

    msg["List-Unsubscribe"] = build_list_unsubscribe_header_value(
        unsubscribe_url,
        lead_id=lead_id,
        lead_email=lead_email,
    )

    if is_https:
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg["Precedence"] = "bulk"

    if campaign_id:
        msg["List-Id"] = f"<campaign.{campaign_id}.evecta>"
        msg["Feedback-ID"] = f"campaign:{campaign_id}:evecta"
