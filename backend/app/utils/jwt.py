from datetime import datetime, timezone, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import re
import uuid
from typing import Tuple, Any, Dict
from app.core.config import get_settings

# Load settings
settings = get_settings()

# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Real bcrypt hash used only for timing equalization when email is unknown.
# Not a real account password — verifying against it never grants access.
_DUMMY_PASSWORD_HASH = pwd_context.hash("evecta-timing-dummy-not-a-real-password")


def is_bcrypt_hash(value: str) -> bool:
    """True if value looks like a bcrypt modular crypt hash."""
    if not value or not isinstance(value, str):
        return False
    return bool(re.match(r"^\$2[aby]?\$\d{2}\$[./A-Za-z0-9]{53}$", value.strip()))


# PASSWORD HASHING & VERIFICATION
def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt (one-way; cannot recover plaintext)."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against the hashed version."""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_dummy_password_hash() -> str:
    """Return a real bcrypt hash for login timing equalization."""
    return _DUMMY_PASSWORD_HASH


# PASSWORD VALIDATION
def validate_password_not_email(password: str, email: str) -> Tuple[bool, str]:
    """
    Validate that password meets complexity criteria and doesn't contain email.
    
    Rules:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    - Password cannot be exactly the same as email
    - Password cannot contain email domains (gmail, yahoo, etc.)
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    if not any(char.isupper() for char in password):
        return False, "Password must include at least one uppercase letter"
    
    if not any(char.islower() for char in password):
        return False, "Password must include at least one lowercase letter"
    
    if not any(char.isdigit() for char in password):
        return False, "Password must include at least one number"
    
    import string
    if not any(char in string.punctuation for char in password):
        return False, "Password must include at least one special character"

    password_lower = password.lower().strip()
    email_lower = email.lower().strip()
    
    # Check if password is exactly the same as email
    if password_lower == email_lower:
        return False, "Password cannot be the same as your email address"
    
    # Common email domains to check for (case-insensitive)
    email_domains = [
        "gmail", "yahoo", "outlook", "hotmail", "email", "mail", 
        "icloud", "protonmail", "aol", "live", "msn", "ymail",
        "zoho", "gmx", "yandex", "rediffmail", "inbox"
    ]
    
    # Check if password contains any email domain
    for domain in email_domains:
        if domain in password_lower:
            return False, f"Password cannot contain email domains like '{domain}'. Please choose a more secure password."
    
    # Check if password contains the full email address
    if email_lower in password_lower:
        return False, "Password cannot contain your email address"
    
    return True, ""


# TOKEN CREATION HELPERS
def create_access_token(user_id: uuid.UUID) -> str:
    """Create an access token (short-lived, default 30 min)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID,
    *,
    expire_days: int | None = None,
) -> Tuple[str, uuid.UUID, datetime]:
    """Create a refresh token (long-lived, default from settings)."""
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4()
    days = expire_days if expire_days is not None else settings.REFRESH_TOKEN_EXPIRE_DAYS
    expires_at = now + timedelta(days=days)

    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": str(jti),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, expires_at


def create_token_pair(user_id: uuid.UUID) -> Tuple[str, str]:
    """Return both access and refresh tokens together."""
    access_token = create_access_token(user_id)
    refresh_token, _, _ = create_refresh_token(user_id)
    return access_token, refresh_token


# TOKEN DECODING
def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT token."""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Token decode error: {str(e)}")
