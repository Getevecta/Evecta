from app.core.config import get_settings

settings = get_settings()

GOOGLE_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    # gmail.modify supersedes gmail.readonly and additionally allows label
    # changes — reply fetch removes the UNREAD label after ingesting a message;
    # with readonly that call 403s and the same message is re-fetched forever.
    # Mailboxes connected before this change must be reconnected to re-consent.
    "https://www.googleapis.com/auth/gmail.modify",
]

GOOGLE_OAUTH_CONFIG = {
    "client_id": settings.GOOGLE_CLIENT_ID,
    "client_secret": settings.GOOGLE_CLIENT_SECRET,
    "redirect_uri": settings.MAILBOX_GOOGLE_REDIRECT_URI,
    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
}
