"""Detect Celery at-least-once redelivery of a send that already went out."""
from __future__ import annotations

from datetime import datetime


def duplicate_send_skip_reason(
    *,
    smtp_started_at: datetime | None,
    has_successful_activity: bool,
) -> str | None:
    """Return why SMTP must not run again, or None if this is the first attempt.

    Celery acks late: a worker can deliver the message, SMTP can succeed, then
    the process can die before the job row is marked SENT. Redelivery must not
    treat a still-SENDING row as a fresh send.
    """
    if has_successful_activity:
        return "already_sent_activity"
    if smtp_started_at is not None:
        return "smtp_already_started"
    return None
