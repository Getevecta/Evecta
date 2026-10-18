from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, field_validator
from uuid import UUID

# Dropdown Options
EXPERIENCE_LEVELS = ["beginner", "intermediate", "expert", "other"]
LEAD_GEN_EXPECTATIONS = ["1-50", "50-100", "50-200", "200-500", "other"]


# BASE SCHEMA (Shared fields)
class CompanyBase(BaseModel):
    # STEP 1 — Identity
    role: Optional[str] = None
    company_name: Optional[str] = None
    company_size: Optional[str] = None
    company_website: Optional[str] = None

    # STEP 2 — Target Audience
    target_industry: Optional[str] = None
    target_specific_business: Optional[str] = None
    target_location: Optional[str] = None

    # STEP 3 — Experience & Usage
    experience_with_lead_gen_tools: Optional[str] = None
    lead_generation_expect_monthly: Optional[str] = None

    # Scraper / AI fields
    industry: Optional[str] = None
    company_description: Optional[str] = None
    products_and_services: Optional[List[Dict[str, Any]]] = None
    business_offers: Optional[List[str]] = None
    unique_selling_point: Optional[List[str]] = None
    customer_goals: Optional[List[str]] = None
    problems_solved: Optional[List[str]] = None
    benefits: Optional[List[str]] = None
    achievements: Optional[List[str]] = None     
    business_email: Optional[str] = None
    # Address
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None

    # DROPDOWN VALIDATION
    @field_validator("experience_with_lead_gen_tools")
    def validate_experience(cls, value):
        if value and value not in EXPERIENCE_LEVELS:
            raise ValueError(f"Invalid experience level: {value}")
        return value

    @field_validator("lead_generation_expect_monthly")
    def validate_expectation(cls, value):
        if value and value not in LEAD_GEN_EXPECTATIONS:
            raise ValueError(f"Invalid monthly expectation: {value}")
        return value


# CREATE SCHEMA (Popup Wizard Submit)
# Scraper fields NOT required here.
class CompanyCreate(CompanyBase):
    # STEP 1
    role: str
    company_name: str
    company_size: str

    # STEP 2
    target_industry: str
    target_location: str

    # target_specific_business is optional by design
    # STEP 3
    experience_with_lead_gen_tools: str
    lead_generation_expect_monthly: str


# UPDATE SCHEMA (Profile Settings)
# All fields optional
class CompanyUpdate(CompanyBase):
    pass


# RESPONSE SCHEMA (Dashboard / Profile)
class CompanyResponse(CompanyBase):
    id: UUID
    user_id: UUID

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
