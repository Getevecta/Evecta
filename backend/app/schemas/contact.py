from pydantic import BaseModel, EmailStr, Field


class ContactFormRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr
    company_name: str | None = Field(None, max_length=200)
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1, max_length=5000)

    model_config = {"extra": "ignore"}


class ContactFormResponse(BaseModel):
    message: str
