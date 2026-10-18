from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY

from app.database.base import Base


class OvertureCategory(Base):
    """
    The official Overture Places category taxonomy (reference data).

    Seeded from Overture's published category CSV and re-seeded on each release.
    Used to (a) validate that a resolved category code is real, and (b) fuzzy-match
    long-tail user terms against display names via pg_trgm.
    """

    __tablename__ = "overture_categories"
    # GIN trigram indexes for fuzzy similarity() search — declared here so Alembic
    # autogenerate recognizes them (otherwise it tries to DROP them every run).
    __table_args__ = (
        Index(
            "ix_overture_categories_display_trgm", "display_name",
            postgresql_using="gin", postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_overture_categories_code_trgm", "code",
            postgresql_using="gin", postgresql_ops={"code": "gin_trgm_ops"},
        ),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # The Overture category code, e.g. "child_care_and_day_care", "pizza_restaurant".
    code = Column(String(128), nullable=False, unique=True, index=True)
    # Human-readable label, used for trigram fuzzy matching of long-tail terms.
    display_name = Column(String(255), nullable=True)
    # Hierarchy path, e.g. ["eat_and_drink", "restaurant"] — lets a broad term map
    # to all its descendant leaves.
    ancestors = Column(ARRAY(String), nullable=True)
    # Marks a broad/top-of-hierarchy category vs a specific leaf (optional convenience).
    is_primary_level = Column(Boolean, nullable=False, default=False)


class OvertureCategoryAlias(Base):
    """
    User-language → Overture category codes (the dynamic, growing table).

    Seeded from the in-code OVERTURE_CATEGORY_MAP plus known phrasing variants, then
    grown automatically: a search whose industry isn't aliased is resolved once
    (fuzzy match / LLM) and stored here, so the next identical phrasing is instant.

    `alias` is the NORMALIZED user term so "childcare centre" and "childcare" can map
    to the same codes → the same category_key → a warm cache hit.
    """

    __tablename__ = "overture_category_aliases"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    alias = Column(String(160), nullable=False, unique=True, index=True)
    category_codes = Column(ARRAY(String), nullable=False)

    # 'seed' | 'learned' | 'manual'
    source = Column(String(16), nullable=False, default="learned", index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    hit_count = Column(Integer, nullable=False, default=0)

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
