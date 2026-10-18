"""Build campaign MIME with List-Unsubscribe headers before Content-Type."""

from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formatdate
from urllib.parse import urlparse
import base64

from app.models.mailbox import MailboxType
from app.core.config import get_settings
from app.utils.email_headers import build_list_unsubscribe_header_value
from app.utils.header_safety import SUBJECT_MAX_LENGTH, require_safe_header


def build_campaign_mime_bytes(
    *,
    html_content: str,
    subject: str,
    from_addr: str,
    to_email: str,
    message_id: str,
    unsubscribe_url: str | None,
    campaign_id: str,
    lead_id: str,
    mailbox_type: MailboxType,
    reply_to: str | None = None,
    lead_email: str | None = None,
) -> bytes:
    """
    RFC 8058: List-Unsubscribe headers must appear before Content-Type so SES
    Easy DKIM can include them in the signature h= tag (required by Gmail).

    Header values are validated through EmailMessage (rejects embedded newlines)
    then serialized in a fixed order so SES Easy DKIM keeps List-Unsubscribe in h=.
    """
    subject = require_safe_header(subject, name="Subject", max_length=SUBJECT_MAX_LENGTH)
    from_addr = require_safe_header(from_addr, name="From")
    to_email = require_safe_header(to_email, name="To")
    message_id = require_safe_header(message_id, name="Message-ID")
    if reply_to:
        reply_to = require_safe_header(reply_to, name="Reply-To")
    if unsubscribe_url:
        unsubscribe_url = require_safe_header(unsubscribe_url, name="List-Unsubscribe")
    if campaign_id:
        campaign_id = require_safe_header(str(campaign_id), name="Campaign-Id")
    if lead_id:
        lead_id = require_safe_header(str(lead_id), name="Lead-Id")
    if lead_email:
        lead_email = require_safe_header(lead_email, name="Lead-Email")

    parsed = urlparse(unsubscribe_url) if unsubscribe_url else None
    use_one_click = bool(unsubscribe_url and parsed and parsed.scheme == "https")

    # Force Python's header parser to reject CR/LF before we emit raw bytes.
    probe = EmailMessage(policy=SMTP)
    probe["Subject"] = subject
    probe["From"] = from_addr
    probe["To"] = to_email
    probe["Message-ID"] = message_id
    if reply_to:
        probe["Reply-To"] = reply_to

    header_lines: list[str] = []

    # List-Unsubscribe must be first in the MIME header block so SES Easy DKIM
    # includes list-unsubscribe + list-unsubscribe-post in the signature h= tag.
    # Gmail only shows inbox-hover / header Unsubscribe when both are DKIM-signed.
    if use_one_click:
        list_unsub = build_list_unsubscribe_header_value(
            unsubscribe_url,
            lead_id=lead_id,
            lead_email=lead_email or to_email,
        )
        require_safe_header(list_unsub, name="List-Unsubscribe")
        header_lines.append(f"List-Unsubscribe: {list_unsub}")
        header_lines.append("List-Unsubscribe-Post: List-Unsubscribe=One-Click")
        header_lines.append("Precedence: bulk")
        if campaign_id:
            header_lines.append(f"List-Id: <campaign.{campaign_id}.evecta>")
            header_lines.append(f"Feedback-ID: campaign:{campaign_id}:evecta")

    header_lines.extend(
        [
            f"Subject: {probe['Subject']}",
            f"From: {probe['From']}",
            f"To: {probe['To']}",
            f"Message-ID: {probe['Message-ID']}",
            f"Date: {formatdate(localtime=True)}",
        ]
    )

    if reply_to:
        header_lines.append(f"Reply-To: {probe['Reply-To']}")
    ses_config_set = get_settings().SES_CONFIGURATION_SET
    if mailbox_type == MailboxType.SYSTEM and ses_config_set:
        header_lines.append(
            f"X-SES-CONFIGURATION-SET: {require_safe_header(ses_config_set, name='X-SES-CONFIGURATION-SET')}"
        )

    header_lines.extend(
        [
            "MIME-Version: 1.0",
            "Content-Type: text/html; charset=utf-8",
            "Content-Transfer-Encoding: base64",
        ]
    )

    body = base64.b64encode(html_content.encode("utf-8")).decode("ascii")
    # Headers and body MUST be separated by a blank line (CRLF CRLF), otherwise
    # mail clients parse the base64 body as a malformed header and show no content.
    header_block = "\r\n".join(header_lines)
    return (header_block + "\r\n\r\n" + body).encode("utf-8")
