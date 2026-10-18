"""AWS SNS URL trust checks — host-anchored, not amazonaws.com suffix matches."""
from __future__ import annotations

import re
from urllib.parse import urlparse

# AWS SNS hosts always look like sns.<region>.amazonaws.com — anchored,
# not a suffix match, so an S3 bucket URL (which also ends in
# "amazonaws.com") can never pass.
_SNS_HOSTNAME_PATTERN = re.compile(r"^sns\.[a-z0-9-]{1,20}\.amazonaws\.com(\.cn)?$")
_SNS_CERT_PATH_PATTERN = re.compile(r"^/SimpleNotificationService-[0-9a-f]{32}\.pem$")


def _is_trusted_sns_host(url: str) -> bool:
    """True only for a genuine AWS SNS host, HTTPS-only."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    return bool(_SNS_HOSTNAME_PATTERN.match((parsed.hostname or "").lower()))


def _is_trusted_sns_cert_url(url: str) -> bool:
    """SigningCertURL must additionally match AWS's certificate filename pattern."""
    if not _is_trusted_sns_host(url):
        return False
    return bool(_SNS_CERT_PATH_PATTERN.match(urlparse(url).path))


def parse_allowed_sns_topic_arns(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def sns_topic_is_permitted(topic_arn: str | None, allowed_raw: str | None) -> bool:
    """Fail closed: empty allowlist or unknown TopicArn is rejected."""
    allowed = parse_allowed_sns_topic_arns(allowed_raw)
    if not allowed:
        return False
    return (topic_arn or "") in allowed
