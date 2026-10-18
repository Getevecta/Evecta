"""Single place that mutates EmailActivity tracking state.

Every tracking entry point (tracking-pixel endpoint, SES webhook) must go
through ``apply_email_event`` instead of flipping columns directly. Rules:

- The boolean columns (delivered/opened/clicked/bounced) are the source of
  truth; ``status`` is always derived from them, never written ad hoc.
- BOUNCED and FAILED are terminal for ``status``: a later scanner click or
  open never upgrades a bounced/failed row back to an engagement status
  (previously a Click event overwrote BOUNCED).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.email_activity import EmailActivity, EmailStatus

# Event names accepted by apply_email_event
EVENT_DELIVERY = "delivery"
EVENT_BOUNCE = "bounce"
EVENT_COMPLAINT = "complaint"
EVENT_OPEN = "open"
EVENT_CLICK = "click"


def _derive_status(activity: EmailActivity) -> EmailStatus:
    if activity.bounced:
        return EmailStatus.BOUNCED
    if activity.status == EmailStatus.FAILED:
        # Terminal: set on send failure or complaint; engagement never clears it.
        return EmailStatus.FAILED
    if activity.clicked:
        return EmailStatus.CLICKED
    if activity.opened:
        return EmailStatus.OPENED
    return EmailStatus.SENT


def apply_email_event(
    activity: EmailActivity,
    event: str,
    occurred_at: datetime | None = None,
) -> None:
    """Apply a tracking event to an activity row. Does NOT commit."""
    now = datetime.now(timezone.utc)
    occurred_at = occurred_at or now

    if event == EVENT_DELIVERY:
        activity.delivered = True
        if activity.delivered_at is None:
            activity.delivered_at = occurred_at

    elif event == EVENT_BOUNCE:
        activity.bounced = True

    elif event == EVENT_COMPLAINT:
        # Preserve historical behaviour: complaints mark the send FAILED.
        activity.status = EmailStatus.FAILED

    elif event == EVENT_OPEN:
        activity.opened = True
        activity.delivered = True  # an open implies delivery
        if activity.first_opened_at is None:
            activity.first_opened_at = occurred_at
        activity.open_count = (activity.open_count or 0) + 1

    elif event == EVENT_CLICK:
        activity.clicked = True
        activity.opened = True  # a click implies an open
        activity.delivered = True
        if activity.first_opened_at is None:
            activity.first_opened_at = occurred_at

    else:
        raise ValueError(f"Unknown email event: {event!r}")

    activity.status = _derive_status(activity)
    activity.updated_at = now
