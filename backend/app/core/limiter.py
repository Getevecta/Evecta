from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from jose import JWTError, jwt
from app.core.config import get_settings

settings = get_settings()


def get_user_or_ip(request: Request) -> str:
    """Use user_id from JWT if present, otherwise fall back to IP address."""
    auth: str = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):]
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                return f"user:{user_id}"
        except JWTError:
            pass
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_user_or_ip,
    storage_uri=settings.redis_cache_url
)
