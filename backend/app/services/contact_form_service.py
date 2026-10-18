import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import Any, Mapping

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Stripe Customer Portal cancellation survey: subscription.cancellation_details.feedback
# https://docs.stripe.com/api/subscriptions/object#subscription_object-cancellation_details
STRIPE_PORTAL_FEEDBACK_LABELS: dict[str, str] = {
    "too_expensive": "Too expensive",
    "missing_features": "Missing features",
    "unused": "Unused / no longer need it",
    "too_complex": "Too complex to use",
    "low_quality": "Low quality",
    "customer_service": "Customer service",
    "switched_service": "Switched to another product / found an alternative",
    "other": "Other",
}


def send_contact_form_email(
    full_name: str,
    email: str,
    company_name: str | None,
    subject: str,
    message: str,
) -> bool:
    """
    Notify Evecta inbox when someone submits the public contact form.
    Uses the same APP_SMTP_* settings as OTP / billing notification mail.
    """
    settings = get_settings()
    inbox = (settings.CONTACT_INBOX_EMAIL or "").strip() or "mail@evecta.io"

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD or not settings.SMTP_FROM_EMAIL:
        logger.warning("Contact form: SMTP not configured — email not sent.")
        return False

    company_line = (company_name or "").strip() or "(not provided)"

    body = f"""New message from the Evecta contact page

Name: {full_name}
Email: {email}
Company: {company_line}
Subject: {subject}

Message:
{message}
"""

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = inbox
    msg["Subject"] = f"[Contact form] {subject}"
    msg["Reply-To"] = formataddr((full_name, email)) if full_name else email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()

        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, inbox, msg.as_string())
        server.quit()
        logger.info("Contact form email sent to %s (from %s)", inbox, email)
        return True
    except smtplib.SMTPException as e:
        logger.error("Contact form SMTP error: %s", e)
        return False
    except Exception as e:
        logger.error("Contact form send failed: %s", e)
        return False


def send_cancellation_feedback_email(
    user_email: str,
    user_name: str,
    reason: str,
    details: str | None,
) -> bool:
    """
    Send subscription cancellation feedback to the Evecta inbox (same as contact form).
    """
    settings = get_settings()
    inbox = (settings.CONTACT_INBOX_EMAIL or "").strip() or "mail@evecta.io"

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD or not settings.SMTP_FROM_EMAIL:
        logger.warning("Cancellation feedback: SMTP not configured — email not sent.")
        return False

    extra = (details or "").strip() or "(none)"

    body = f"""Cancellation feedback (Stripe billing portal)

User: {user_name}
Email: {user_email}

Reason selected:
{reason}

Additional feedback:
{extra}
"""

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = inbox
    msg["Subject"] = f"[Cancellation feedback] {reason[:80]}"
    msg["Reply-To"] = formataddr((user_name, user_email)) if user_name else user_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()

        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, inbox, msg.as_string())
        server.quit()
        logger.info("Cancellation feedback sent to %s (from %s)", inbox, user_email)
        return True
    except smtplib.SMTPException as e:
        logger.error("Cancellation feedback SMTP error: %s", e)
        return False
    except Exception as e:
        logger.error("Cancellation feedback send failed: %s", e)
        return False


def _format_cancel_at_utc(cancel_at_unix: int | None) -> str:
    if not cancel_at_unix:
        return "(not set)"
    try:
        dt = datetime.fromtimestamp(int(cancel_at_unix), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(cancel_at_unix)


def send_stripe_portal_cancellation_survey_email(
    user_email: str,
    user_name: str,
    subscription_id: str,
    cancel_at_unix: int | None,
    cancellation_details: Mapping[str, Any] | None,
) -> bool:
    """
    Email team inbox with Stripe Customer Portal cancellation survey answers
    (cancellation_details: feedback, comment, reason) — not the in-app feedback modal.
    """
    settings = get_settings()
    inbox = (settings.CONTACT_INBOX_EMAIL or "").strip() or "mail@evecta.io"

    if not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD or not settings.SMTP_FROM_EMAIL:
        logger.warning("Stripe cancellation survey: SMTP not configured — email not sent.")
        return False

    cd: dict = dict(cancellation_details) if isinstance(cancellation_details, Mapping) else {}
    raw_feedback = (cd.get("feedback") or "").strip() or None
    comment = (cd.get("comment") or "").strip() or None
    reason = (cd.get("reason") or "").strip() or None

    if not raw_feedback and not comment:
        return False

    label = STRIPE_PORTAL_FEEDBACK_LABELS.get(raw_feedback, raw_feedback) if raw_feedback else "(not selected)"
    subj_feedback = (label or raw_feedback or "other")[:80]
    when = _format_cancel_at_utc(cancel_at_unix)

    body = f"""Cancellation survey — Stripe Customer Portal

A subscriber scheduled cancellation and answered Stripe’s survey (in the billing portal).

User: {user_name}
User email: {user_email}
Stripe subscription ID: {subscription_id or "—"}
Access ends (cancel_at): {when}

Reason category (from Stripe list):
{label}
(Stripe value: {raw_feedback or "—"})

Free-text comment (if any):
{comment or "—"}

Stripe cancellation_details.reason: {reason or "—"}
"""

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = inbox
    msg["Subject"] = f"[Cancellation — Portal survey] {subj_feedback}"
    msg["Reply-To"] = formataddr((user_name, user_email)) if user_name else user_email
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()

        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, inbox, msg.as_string())
        server.quit()
        logger.info("Stripe portal cancellation survey email sent to %s (user %s)", inbox, user_email)
        return True
    except smtplib.SMTPException as e:
        logger.error("Stripe cancellation survey SMTP error: %s", e)
        return False
    except Exception as e:
        logger.error("Stripe cancellation survey send failed: %s", e)
        return False
