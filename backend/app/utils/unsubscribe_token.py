import hashlib
import hmac
import secrets
import time

# Token valid for 1 year — long enough for email campaigns
_TOKEN_TTL_SECONDS = 365 * 24 * 3600


def _get_secret() -> bytes:
    from app.core.config import get_settings
    return get_settings().SECRET_KEY.encode()


def generate_unsubscribe_token(lead_id: str, email: str) -> str:
    """Generate an HMAC-signed token with expiry. Format: expiry.signature"""
    expiry = int(time.time()) + _TOKEN_TTL_SECONDS
    payload = f"{lead_id}:{email}:{expiry}"
    sig = hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{sig}"


def verify_unsubscribe_token(token: str, lead_id: str, email: str) -> bool:
    """Verify HMAC signature and expiry. Constant-time comparison."""
    try:
        expiry_str, sig = token.split(".", 1)
        expiry = int(expiry_str)
    except (ValueError, AttributeError):
        return False

    if time.time() > expiry:
        return False

    payload = f"{lead_id}:{email}:{expiry_str}"
    expected_sig = hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(sig, expected_sig)
