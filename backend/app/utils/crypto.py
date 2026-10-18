from cryptography.fernet import Fernet, InvalidToken
from app.core.config import get_settings

settings = get_settings()

# Fernet key must be 32 url-safe base64-encoded bytes
fernet = Fernet(settings.MAILBOX_SECRET_KEY)


def encrypt_secret(value: str) -> str:
    """
    Encrypt sensitive value before storing in DB.
    """
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """
    Decrypt sensitive value when needed (SMTP / IMAP).
    """
    return fernet.decrypt(value.encode()).decode()


def decrypt_secret_compat(value: str) -> str:
    """Decrypt Fernet ciphertext; return as-is for legacy plaintext rows."""
    if not value:
        return value
    try:
        return decrypt_secret(value)
    except (InvalidToken, ValueError, TypeError):
        return value
