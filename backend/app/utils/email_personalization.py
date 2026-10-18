"""Lead placeholder substitution and HTML formatting for outbound campaign mail.

Lives in utils so services and Celery tasks share one implementation — tasks
import from here, not the reverse.
"""
from __future__ import annotations

import html as html_module
import re
from typing import Any, Mapping

from app.models.lead import Lead

SAMPLE_LEAD_VALUES: dict[str, str] = {
    "business_name": "Sample Company",
    "email": "sample@company.com",
    "address": "123 Main St, City",
    "industry": "Technology",
    "website": "https://sample-company.com",
    "contact_number": "+1 (555) 123-4567",
}


def _placeholder_mapping(lead_obj: Lead | Mapping[str, Any] | None) -> dict[str, Any]:
    if lead_obj is None:
        return dict(SAMPLE_LEAD_VALUES)
    if isinstance(lead_obj, Mapping):
        return {
            attr: value
            for attr, value in lead_obj.items()
            if not str(attr).startswith("_") and value is not None
        }
    return {
        attr: value
        for attr, value in lead_obj.__dict__.items()
        if not attr.startswith("_") and value is not None
    }


def replace_placeholders(template: str, lead_obj: Lead | Mapping[str, Any] | None = None) -> str:
    """Replace ``{{ field }}`` tokens that match Lead attributes (or sample data)."""
    if not template:
        return template or ""
    content = template
    for attr, value in _placeholder_mapping(lead_obj).items():
        placeholder = f"{{{{ {attr} }}}}"
        if placeholder in content:
            content = content.replace(placeholder, str(value))
    return content


def format_plain_text_as_html(plain_text: str) -> str:
    """
    Convert plain text with line breaks to properly formatted HTML email content.
    Strips any existing HTML tags (especially <p> tags) and converts to clean HTML.

    - Strips all HTML tags first (handles both <p> and &lt;p&gt;)
    - Unescapes HTML entities if needed
    - Escapes HTML special characters
    - Converts newlines to <br> tags
    - Wraps in proper HTML structure for email clients
    """
    if not plain_text:
        return ""

    # Strip any BOM or invisible characters
    cleaned = plain_text.strip().lstrip("\ufeff")

    # First, unescape any HTML entities (in case content was double-escaped)
    # This handles cases where <p> became &lt;p&gt;
    try:
        unescaped = html_module.unescape(cleaned)
    except Exception:
        unescaped = cleaned

    # Preserve line breaks from <br> before stripping tags (so content using <br> keeps paragraphs)
    unescaped = re.sub(r"<br\s*/?>", "\n", unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r"<br>", "\n", unescaped, flags=re.IGNORECASE)

    # CRITICAL: Remove ALL <p> tags FIRST (before removing other tags)
    # This ensures <p> tags are completely removed regardless of attributes
    unescaped = re.sub(r"<p[^>]*>", "", unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r"</p>", "", unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r"<P[^>]*>", "", unescaped, flags=re.IGNORECASE)
    unescaped = re.sub(r"</P>", "", unescaped, flags=re.IGNORECASE)

    # Remove all other HTML tags to get plain text
    # This handles cases where content has other HTML tags from templates
    plain_content = re.sub(r"<[^>]+>", "", unescaped)

    # Also remove any remaining escaped HTML entities that might have been missed
    # Handle escaped <p> tags specifically
    plain_content = re.sub(r"&lt;p[^&]*&gt;", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"&lt;/p&gt;", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"&lt;P[^&]*&gt;", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"&lt;/P&gt;", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"&lt;[^&]+&gt;", "", plain_content)
    plain_content = plain_content.replace("&lt;", "").replace("&gt;", "")

    # FINAL SAFETY CHECK: Remove any remaining <p> tags (case-insensitive)
    # This is a triple-check to guarantee no p tags slip through
    plain_content = re.sub(r"<p[^>]*>", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"</p>", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"<P[^>]*>", "", plain_content, flags=re.IGNORECASE)
    plain_content = re.sub(r"</P>", "", plain_content, flags=re.IGNORECASE)

    # Replace multiple whitespace/newlines with single newline
    plain_content = re.sub(r"\n\s*\n+", "\n\n", plain_content)
    plain_content = plain_content.strip()

    # If content has no paragraph breaks (e.g. server-stored single line), add line breaks after sentences
    # so the email does not render as one block (period + space + capital letter = sentence boundary).
    if plain_content and "\n" not in plain_content:
        plain_content = re.sub(r"\.\s+([A-Z])", r".\n\n\1", plain_content)
    elif plain_content and plain_content.count("\n") < 2:
        plain_content = re.sub(r"\.\s+([A-Z])", r".\n\n\1", plain_content)

    # Escape HTML special characters to prevent injection
    escaped_text = html_module.escape(plain_content)

    # Convert newlines to <br> tags
    html_content = escaped_text.replace("\n", "<br>")

    # Wrap in proper HTML structure for email clients to render naturally
    # This ensures the email looks normal without visible tags
    wrapped_content = (
        f'<div style="font-family: system-ui, -apple-system, BlinkMacSystemFont, '
        f"'Segoe UI', Roboto, sans-serif; font-size: 14px; line-height: 1.6; "
        f'color: #111827;">{html_content}</div>'
    )

    return wrapped_content


def build_footer(
    unsubscribe_url: str,
    subscribe_url: str = "",
    sender_name: str = "Evecta Outreach",
    preferences_url: str = "",
) -> str:
    extra_link = ""
    if preferences_url:
        extra_link = f"""
            <a href="{preferences_url}" style="display: inline-block; padding: 6px 12px; border-radius: 999px; border: 1px solid #d1d5db; text-decoration: none; color: #374151;">
                Manage email preferences
            </a>"""
    # subscribe_url is accepted for call-site compatibility; footer currently exposes unsubscribe only.
    _ = subscribe_url
    return f"""
    <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">
        <p style="margin: 0 0 8px 0;">
            You are receiving this email from <strong>{sender_name}</strong> as part of a campaign.
        </p>
        <div style="display: inline-flex; gap: 8px; margin-top: 4px;">
            <a href="{unsubscribe_url}" style="display: inline-block; padding: 6px 12px; border-radius: 999px; border: 1px solid #d1d5db; text-decoration: none; color: #374151;">
                Unsubscribe
            </a>{extra_link}
        </div>
    </div>
    """
