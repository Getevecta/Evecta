"""Shared duplicate detection for Lead imports and promotions."""
from __future__ import annotations

from typing import Optional

_PLACEHOLDER_EMAILS = frozenset({"n/a", "na", "none", "-", "null", "no email", "noemail"})


def normalize_email(email: Optional[str]) -> Optional[str]:
    if email is None:
        return None
    value = str(email).strip()
    if not value:
        return None
    if value.lower() in _PLACEHOLDER_EMAILS:
        return None
    return value.lower()


def normalize_business_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    value = str(name).strip()
    return value.lower() if value else None


def is_duplicate_lead(
    email: Optional[str],
    business_name: Optional[str],
    existing_emails: set[str],
    existing_names_no_email: set[str],
) -> bool:
    norm_email = normalize_email(email)
    norm_name = normalize_business_name(business_name)
    if norm_email:
        return norm_email in existing_emails
    if norm_name:
        return norm_name in existing_names_no_email
    return False


def register_lead_keys(
    email: Optional[str],
    business_name: Optional[str],
    existing_emails: set[str],
    existing_names_no_email: set[str],
) -> None:
    """Track a lead that will be saved so later rows in the same batch are deduped."""
    norm_email = normalize_email(email)
    norm_name = normalize_business_name(business_name)
    if norm_email:
        existing_emails.add(norm_email)
    elif norm_name:
        existing_names_no_email.add(norm_name)
