from urllib.parse import urlencode

from app.core.config import get_settings
from app.utils.unsubscribe_token import generate_unsubscribe_token


def build_unsubscribe_urls(lead_id: str, email: str, token: str | None = None) -> dict[str, str]:
    """
    Build unsubscribe URLs for email headers (one-click POST) and footer (confirm page).

    Headers must use one_click_url (HTTPS, no HTML interstitial on GET).
    Footer links use confirm_url (shows confirmation UI).
    """
    token = token or generate_unsubscribe_token(lead_id, email)
    base = get_settings().get_unsubscribe_base_url().rstrip("/")
    params = urlencode({"email": email, "lead_id": lead_id, "token": token})

    return {
        "one_click_url": f"{base}/one-click?{params}",
        "confirm_url": f"{base}?{params}",
        "subscribe_url": f"{base}/toggle?{params}&action=subscribe",
        "token": token,
    }
