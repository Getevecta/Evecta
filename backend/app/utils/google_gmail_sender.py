import base64
from datetime import datetime, timezone, timedelta
from app.core.http_client import mailbox_cycle_client
from app.services.google_gmail_token_service import google_access_token_plain, refresh_google_token
from sqlalchemy.ext.asyncio import AsyncSession


async def send_via_gmail_api(
    *,
    mailbox,
    raw_mime: bytes,
    db: AsyncSession | None = None,
):
    """Send pre-built raw MIME (preserves List-Unsubscribe header order).

    Refresh the access token *before* calling this if *db* is not provided.
    """
    expires = mailbox.google_token_expires_at
    if expires is None or expires <= datetime.now(timezone.utc) + timedelta(minutes=2):
        if db is None:
            raise RuntimeError(
                "Gmail access token expired; refresh it before sending without a DB session"
            )
        await refresh_google_token(mailbox=mailbox, db=db)

    raw = base64.urlsafe_b64encode(raw_mime).decode()

    client = mailbox_cycle_client()
    res = await client.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={
            "Authorization": f"Bearer {google_access_token_plain(mailbox)}",
            "Content-Type": "application/json",
        },
        json={"raw": raw},
    )

    res.raise_for_status()
