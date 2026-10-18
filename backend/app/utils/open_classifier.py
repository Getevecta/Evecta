"""Shared classifier for email open/click events.

Decides whether an open/click was performed by a human or by a machine
(security scanner, link-preview bot, mail-provider image proxy, or the
Apple Mail Privacy Protection prefetch cache).

Used by BOTH tracking entry points so the rules live in exactly one place:
- the tracking-pixel endpoint (USER mailbox sends)   -> app/api/v1/email_insight.py
- the SES -> SNS event webhook (SYSTEM mailbox sends) -> app/api/v1/webhook_ses.py
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import Enum


class OpenClassification(str, Enum):
    HUMAN = "human"
    BOT = "bot"                # security scanner / crawler / prefetch
    APPLE_MPP = "apple_mpp"    # Apple Mail Privacy Protection proxy prefetch


# Known email security scanners and bot user-agent patterns.
# NOTE: Do NOT treat GoogleImageProxy as a bot — Gmail always fetches
# tracking pixels through that proxy when a recipient displays the message.
# Instant prefetch is still filtered by MACHINE_OPEN_WINDOW below.
# (Moved here from email_insight.py / webhook_brevo.py where it was duplicated.)
BOT_UA_PATTERNS = re.compile(
    r"(googlebot|bingpreview|msnbot|"
    r"yahoo.*mail|outlooksafebrowsing|microsoft.*preview|safelinks|"
    r"barracuda|proofpoint|mimecast|ironport|symantec|messagelabs|"
    r"cloudmark|spamassassin|postini|appriver|reflexion|"
    r"preview|prefetch|bot|crawler|spider|scanner|validator|"
    r"feedfetcher|wget|curl|python-requests|java\/|go-http-client)",
    re.IGNORECASE,
)

# Apple MPP proxy fetches pixels with a truncated WebKit UA that carries no
# browser/version suffix. Real Safari/Mail UAs continue with "Version/…",
# "Safari/…" or "Mobile/…" after the KHTML segment.
_APPLE_WEBKIT_RE = re.compile(r"applewebkit/[\d.]+ \(khtml, like gecko\)\s*$", re.IGNORECASE)

# Opens that arrive within this window after delivery are treated as machine
# prefetch — humans do not open mail seconds after the MTA accepts it, but
# scanners and the Apple cache do exactly that.
MACHINE_OPEN_WINDOW = timedelta(seconds=15)


def _is_apple_mpp_user_agent(user_agent: str) -> bool:
    ua = user_agent.strip()
    if ua == "Mozilla/5.0":
        return True
    return bool(_APPLE_WEBKIT_RE.search(ua))


def classify_open(
    user_agent: str | None,
    ip_address: str | None = None,
    occurred_at: datetime | None = None,
    delivered_at: datetime | None = None,
) -> OpenClassification:
    """Classify a single open/click event.

    ``delivered_at`` may be the activity's ``delivered_at`` or, when that is
    unknown (e.g. USER-mailbox sends receive no delivery events), ``sent_at``.
    ``ip_address`` is accepted for future IP-range rules; unused today.
    """
    ua = (user_agent or "").strip()

    # No user agent at all — real mail clients always send one; proxies often don't.
    if not ua:
        return OpenClassification.BOT

    if BOT_UA_PATTERNS.search(ua):
        return OpenClassification.BOT

    if _is_apple_mpp_user_agent(ua):
        return OpenClassification.APPLE_MPP

    # Timing guard: open fired near-instantly after delivery => prefetch.
    if occurred_at is not None and delivered_at is not None:
        try:
            if occurred_at - delivered_at < MACHINE_OPEN_WINDOW:
                return OpenClassification.BOT
        except TypeError:
            # naive/aware datetime mix — skip the timing rule rather than crash
            pass

    return OpenClassification.HUMAN
