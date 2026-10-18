from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from app.database.base import Base


class OverturePlace(Base):
    """
    Cached Overture Maps places — the searchable business catalog.

    This is reference data, NOT user leads. It replaces the role of the Google
    Places API: rows are pulled on-demand for a searched area, cached here, and
    queried with PostGIS (ST_DWithin). A row becomes a *user's lead* only when
    chat_service copies it into lead_log_leads — that table is untouched.

    `source` distinguishes the origin so a future multi-source design (Overture +
    scraped + manual) and the monthly Overture refresh can coexist safely:
    the refresh only updates rows WHERE source = 'overture'.
    """

    __tablename__ = "overture_places"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Overture's stable place id — the upsert/dedup key.
    overture_id = Column(String(64), nullable=False, unique=True, index=True)

    name = Column(String(255), nullable=False, index=True)

    # Flat snake_case leaf category, e.g. "child_care_and_day_care".
    category_primary = Column(String(128), nullable=True, index=True)
    # primary + alternates, for substring category matching.
    categories = Column(ARRAY(String), nullable=True)

    website = Column(String(512), nullable=True)
    phone = Column(String(64), nullable=True)
    address = Column(String(512), nullable=True)
    # City/municipality from Overture's address struct (addresses[0].locality).
    # Reliable city key (vs parsing `address`) for the city tier and for the GEO-4
    # "nearby areas with counts" exhaustion suggestions.
    locality = Column(String(128), nullable=True, index=True)

    # Overture-PROVIDED email (emails[0]). Distinct from a future scraped/enriched
    # email column — the refresh updates THIS one (it's Overture data); the scraped
    # one (added in the dedup/business-master phase) must be excluded from refresh.
    email = Column(String(320), nullable=True)
    # open | closed | (usually NULL). Used to hide closed businesses at query time.
    operating_status = Column(String(32), nullable=True, index=True)
    # Richer category model: leaf + full hierarchy breadcrumb (for sharper matching).
    taxonomy_primary = Column(String(128), nullable=True)
    taxonomy_hierarchy = Column(ARRAY(String), nullable=True)

    # Metadata only — NOT a search gate (any country is allowed).
    country_code = Column(String(2), nullable=True, index=True)
    confidence = Column(Float, nullable=True, index=True)

    # 'overture' | 'scraped' | 'manual' — forward-compat for multi-source.
    source = Column(
        String(20),
        nullable=False,
        default="overture",
        server_default="overture",
        index=True,
    )

    # ── Enrichment (OWNED data — master-catalog design) ────────────────────────
    # Written by the enrichment job, keyed by overture_id. The monthly Overture
    # refresh must NEVER touch these columns (refresh safety rules): it updates
    # Overture-provided fields only. Types match lead_log_leads for compatibility.
    #
    # scraped_email is SEPARATE from `email` (Overture's): serve
    # COALESCE(scraped_email, email); email_source labels how the served email
    # was found ('overture' | 'scraper' | 'hunter' | 'manual' | ...).
    scraped_email = Column(String(320), nullable=True)
    email_source = Column(String(20), nullable=True)
    lead_score = Column(Integer, nullable=True)
    # pending | processing | done | failed; NULL = never enriched (eligible).
    enrichment_status = Column(String(20), nullable=True, index=True)
    enriched_at = Column(DateTime(timezone=True), nullable=True)
    hunter_data = Column(JSONB, nullable=True)
    # Context scraped from the business website (personalization). `services`
    # is comma-joined text, same shape as lead_log_leads.
    services = Column(Text, nullable=True)
    website_summary = Column(Text, nullable=True)
    business_description = Column(Text, nullable=True)

    # POINT in WGS84. spatial_index=True → GeoAlchemy2 creates a GIST index.
    geom = Column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
        nullable=False,
    )

    loaded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,  # refresh / reporting query by load time
    )


class OvertureLoadedArea(Base):
    """
    Registry of which geographic areas have already been pulled from Overture.

    On a search we build the needed bbox and check, via ST_Contains, whether a
    fresh loaded area already covers it. If yes → query overture_places locally.
    If no → cold-load that bbox from Overture, then record it here.
    """

    __tablename__ = "overture_loaded_areas"
    # One row per (area, category): "Gordon + childcare" and "Gordon + restaurant"
    # are tracked separately. The loader upserts ON CONFLICT(area_key, category_key).
    __table_args__ = (
        UniqueConstraint("area_key", "category_key", name="uq_overture_area_category"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Label for the area (e.g. rounded center coords). Coverage dedup is by bbox containment.
    area_key = Column(String(64), nullable=False, index=True)
    # Which category set is loaded for this area (e.g. "child_care|day_care|preschool").
    category_key = Column(String(128), nullable=False, index=True)
    country_code = Column(String(2), nullable=True, index=True)

    # The loaded rectangle — used for ST_Contains coverage checks.
    bbox = Column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True),
        nullable=False,
    )

    place_count = Column(Integer, nullable=False, default=0)

    # True when the last pull hit its row cap → Overture likely has more for this
    # (area, category) than we cached. Drives the exhaustion top-up (§6.11): a user
    # who drains the cache triggers a pull of the next batch. Set False once a pull
    # comes back short (upstream is exhausted). Defaults True so pre-existing areas
    # stay eligible.
    has_more = Column(Boolean, nullable=False, default=True, server_default="true")

    # Freshness check vs OVERTURE_AREA_TTL_DAYS.
    loaded_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Which Overture release this area was loaded from. Non-null (the loader always
    # sets it); indexed so the refresh job can find areas on an older release.
    overture_release = Column(String(32), nullable=False, index=True)
