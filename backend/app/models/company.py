import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    ForeignKey,
    DateTime,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database.base import Base


class Company(Base):
    __tablename__ = "companies"

    # Primary Key
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    __table_args__ = (
        Index("idx_company_user_id", "user_id"),
    )

    # Foreign Key
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Required fields (from popup)
    role = Column(String(100), nullable=False)
    company_name = Column(String(255), nullable=False)
    company_size = Column(String(50), nullable=False)
    company_website = Column(String(255), nullable=True)
    industry = Column(String(255), nullable=True)
    target_industry = Column(String(255), nullable=False)
    target_location = Column(String(255), nullable=False)

    # Optional popup fields
    target_specific_business = Column(Text, nullable=True)

    # Dropdowns (validate in Pydantic, NOT DB)
    experience_with_lead_gen_tools = Column(String(50), nullable=True)
    lead_generation_expect_monthly = Column(String(50), nullable=True)

    # Scraper / AI enrichment fields
    company_description = Column(Text, nullable=True)
    products_and_services = Column(JSONB, nullable=True)
    business_offers = Column(JSONB, nullable=True)        
    unique_selling_point = Column(JSONB, nullable=True)   
    customer_goals = Column(JSONB, nullable=True)         
    problems_solved = Column(JSONB, nullable=True)            
    benefits = Column(JSONB, nullable=True)                  
    achievements = Column(JSONB, nullable=True)
    business_email = Column(String(255), nullable=True)
    
    # Optional address info
    country = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    user = relationship("User", back_populates="company")
