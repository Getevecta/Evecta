from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.google_gmail import GOOGLE_OAUTH_CONFIG
from app.core.http_client import get_http_client
from app.utils.crypto import decrypt_secret, decrypt_secret_compat, encrypt_secret


def store_google_access_token(mailbox, token: str) -> None:
    mailbox.google_access_token = encrypt_secret(token)


def google_access_token_plain(mailbox) -> str:
    return decrypt_secret_compat(mailbox.google_access_token or "")


async def refresh_google_token(
    *,
    mailbox,
    db: AsyncSession,
):
    refresh_token = decrypt_secret(mailbox.google_refresh_token)
    client = get_http_client()
    res = await client.post(
        GOOGLE_OAUTH_CONFIG["token_uri"],
        data={
            "client_id": GOOGLE_OAUTH_CONFIG["client_id"],
            "client_secret": GOOGLE_OAUTH_CONFIG["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )

    if res.status_code != 200:
        raise HTTPException(
            status_code=401,
            detail="Google token refresh failed. Please reconnect Gmail.",
        )

    data = res.json()

    if "access_token" not in data:
        raise HTTPException(
            status_code=401,
            detail="Google did not return a new access token",
        )

    store_google_access_token(mailbox, data["access_token"])
    mailbox.google_token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=data["expires_in"]
    )

    db.add(mailbox)
    await db.commit()
    await db.refresh(mailbox)

    return mailbox
