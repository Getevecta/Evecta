from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerificationRequest(BaseModel):
    code: str
    email: EmailStr  # required to prevent targeting arbitrary user_ids


class OTPResponse(BaseModel):
    message: str
    expires_at: Optional[datetime] = None
    can_resend_in: Optional[int] = None  # seconds


class OTPVerificationResponse(BaseModel):
    success: bool
    message: str
    user_id: Optional[str] = None
    access_token: Optional[str] = None
    token_type: Optional[str] = None
