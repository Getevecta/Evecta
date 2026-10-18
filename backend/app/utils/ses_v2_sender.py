"""Send SYSTEM campaign mail via SES v2 API so List-Unsubscribe headers are DKIM-signed.

Gmail inbox-hover and header Unsubscribe require List-Unsubscribe + List-Unsubscribe-Post
in the DKIM h= tag. SES v2 SendEmail with the Headers field handles this reliably;
raw SMTP often omits them from the signature or SES subscription management overrides them.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SES_SMTP_HOST_RE = re.compile(r"email-smtp\.([a-z0-9-]+)\.amazonaws\.com", re.I)


def resolve_ses_region(smtp_host: str | None, configured_region: str | None) -> str | None:
    if configured_region:
        return configured_region.strip()
    if not smtp_host:
        return None
    match = _SES_SMTP_HOST_RE.search(smtp_host)
    return match.group(1) if match else None


def _ses_v2_client(region: str):
    import boto3

    from app.core.config import get_settings

    settings = get_settings()
    kwargs: dict[str, Any] = {"region_name": region}
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("sesv2", **kwargs)


def _send_ses_v2_sync(
    *,
    region: str,
    from_addr: str,
    to_email: str,
    subject: str,
    html_content: str,
    reply_to: str | None,
    unsubscribe_url: str | None,
    campaign_id: str,
    message_id: str,
    configuration_set: str | None,
) -> dict[str, Any]:
    custom_headers: list[dict[str, str]] = [
        {"Name": "X-Evecta-Message-ID", "Value": message_id},
    ]

    if unsubscribe_url:
        # List-Unsubscribe must be first — Gmail + RFC 8058 require this order.
        custom_headers.extend(
            [
                {"Name": "List-Unsubscribe", "Value": f"<{unsubscribe_url}>"},
                {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
            ]
        )
        if campaign_id:
            custom_headers.extend(
                [
                    {"Name": "List-Id", "Value": f"<campaign.{campaign_id}.evecta>"},
                    {"Name": "Feedback-ID", "Value": f"campaign:{campaign_id}:evecta"},
                ]
            )

    request: dict[str, Any] = {
        "FromEmailAddress": from_addr,
        "Destination": {"ToAddresses": [to_email]},
        "Content": {
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html_content, "Charset": "UTF-8"}},
                "Headers": custom_headers,
            }
        },
    }
    if reply_to:
        request["ReplyToAddresses"] = [reply_to]
    if configuration_set:
        request["ConfigurationSetName"] = configuration_set

    client = _ses_v2_client(region)
    try:
        return client.send_email(**request)
    except Exception as exc:
        if configuration_set and _should_retry_without_config_set(exc):
            logger.warning(
                "SES send with configuration set %r failed (%s) — retrying without it "
                "so List-Unsubscribe is not overridden",
                configuration_set,
                exc,
            )
            request.pop("ConfigurationSetName", None)
            return client.send_email(**request)
        raise


def _should_retry_without_config_set(exc: Exception) -> bool:
    code = ""
    try:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
    except ImportError:
        pass
    if code in {
        "NotFoundException",
        "ConfigurationSetDoesNotExist",
        "ConfigurationSetDoesNotExistException",
    }:
        return True
    message = str(exc).lower()
    return "configurationset" in message or "configuration set" in message


async def send_via_ses_v2(
    *,
    region: str,
    from_addr: str,
    to_email: str,
    subject: str,
    html_content: str,
    reply_to: str | None,
    unsubscribe_url: str | None,
    campaign_id: str,
    message_id: str,
    configuration_set: str | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _send_ses_v2_sync,
        region=region,
        from_addr=from_addr,
        to_email=to_email,
        subject=subject,
        html_content=html_content,
        reply_to=reply_to,
        unsubscribe_url=unsubscribe_url,
        campaign_id=campaign_id,
        message_id=message_id,
        configuration_set=configuration_set,
    )


def ses_v2_api_available(region: str | None) -> bool:
    if not region:
        return False
    try:
        import boto3  # noqa: F401
    except ImportError:
        logger.warning("boto3 not installed — SYSTEM mail will use SMTP (no Gmail hover Unsubscribe)")
        return False

    from app.core.config import get_settings

    settings = get_settings()
    if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
        return True

    try:
        import boto3

        session = boto3.Session()
        return session.get_credentials() is not None
    except Exception:
        return False
