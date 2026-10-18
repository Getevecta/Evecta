"""Session cookie helpers live in session_service, including logout clearing."""
from starlette.responses import Response

from app.services.admin_device_trust import ADMIN_DEVICE_TRUST_COOKIE
from app.services.session_service import clear_auth_cookies, set_auth_cookies


def _cookie_headers(response: Response) -> list[str]:
    return response.headers.getlist("set-cookie")


def test_set_auth_cookies_writes_httponly_access_and_refresh():
    response = Response()
    set_auth_cookies(
        response,
        access_token="access-value",
        refresh_token="refresh-value",
        secure=True,
    )
    headers = _cookie_headers(response)
    assert any(h.startswith("access_token=") and "httponly" in h.lower() for h in headers)
    assert any(h.startswith("refresh_token=") and "httponly" in h.lower() for h in headers)
    assert not any(h.startswith(f"{ADMIN_DEVICE_TRUST_COOKIE}=") for h in headers)


def test_clear_auth_cookies_expires_access_and_refresh_not_device_trust():
    response = Response()
    set_auth_cookies(
        response,
        access_token="access-value",
        refresh_token="refresh-value",
        secure=True,
        device_trust_token="trust-value",
    )
    clear_auth_cookies(response, secure=True)
    headers = _cookie_headers(response)
    expired = [h for h in headers if "Max-Age=0" in h or "max-age=0" in h.lower()]
    assert any("access_token=" in h for h in expired)
    assert any("refresh_token=" in h for h in expired)
    assert not any(ADMIN_DEVICE_TRUST_COOKIE in h and "Max-Age=0" in h for h in expired)
    assert any(h.startswith(f"{ADMIN_DEVICE_TRUST_COOKIE}=") for h in headers)
