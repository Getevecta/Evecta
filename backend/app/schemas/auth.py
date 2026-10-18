from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"
    # Admin login step-up: password OK, tokens withheld until email OTP is verified
    requires_2fa: bool = False
    email: Optional[EmailStr] = None
    message: Optional[str] = None


class AdminLogin2FAVerifyRequest(BaseModel):
    email: EmailStr
    otp_code: str


class AdminLogin2FAResendRequest(BaseModel):
    email: EmailStr


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp_code: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp_code: str
    new_password: str = Field(..., min_length=8, max_length=128)
