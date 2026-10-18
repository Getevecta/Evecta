from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from app.schemas.role import RoleRead

class UserBase(BaseModel):
    email: EmailStr = Field(..., examples=["john@example.com"])
    username: Optional[str] = Field(None, examples=["john_doe"])


class UserCreate(UserBase):
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password is required for local sign-up.",
    )


class UserRead(UserBase):
    id: UUID  
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserListRole(BaseModel):
    """Lightweight role for admin user list (no permissions payload)."""

    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)


class UserList(UserBase):
    id: UUID  
    is_active: bool
    is_superuser: bool
    email_verified: bool = False
    created_at: datetime
    updated_at: datetime
    role_obj: Optional[UserListRole] = None
    full_name: Optional[str] = None
    plan: str = "free"
    plan_billing_interval: Optional[str] = None
    first_login_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UserListPage(BaseModel):
    items: list[UserList]
    total: int
    limit: int
    offset: int


class AdminUserPlanUpdate(BaseModel):
    """Admin complimentary plan change (does not create a Stripe checkout)."""

    plan: str = Field(..., examples=["free", "starter", "growth", "scale"])
    plan_billing_interval: Optional[str] = Field(
        "month",
        examples=["month", "year"],
        description="Billing interval used for credit grant sizing (month or year).",
    )


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128, examples=["currentPassword123"])
    new_password: str = Field(..., min_length=8, max_length=128, examples=["newPassword123"])
        
class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, examples=["john_doe"])
    email: Optional[EmailStr] = Field(None, examples=["john@example.com"])
    full_name: Optional[str] = Field(None, examples=["John Doe"])
    department: Optional[str] = Field(None, examples=["Sales"])
    location: Optional[str] = Field(None, examples=["City, Country"])
    website: Optional[str] = Field(None, examples=["https://yourwebsite.com"])
    bio: Optional[str] = Field(None, max_length=500, examples=["Tell us about yourself"])
    profile_image: Optional[str] = Field(None, examples=["data:image/png;base64,..."])


class AdminUserCreate(BaseModel):
    full_name: str = Field(..., examples=["John Doe"])
    email: EmailStr = Field(..., examples=["john@example.com"])
    username: Optional[str] = Field(None, examples=["john_doe"])
    password: str = Field(..., min_length=8, max_length=128, examples=["StrongPass123"])
    role_id: UUID
    is_active: bool = True
    override_permission_ids: Optional[list[UUID]] = []

    class Config:
        from_attributes = True

class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    role_id: Optional[str] = None
    is_active: Optional[bool] = None
    
    # Optional overrides
    override_permission_ids: Optional[List[str]] = None

    # Optional profile fields
    department: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    bio: Optional[str] = None
    profile_image: Optional[str] = None

        