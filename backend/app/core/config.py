from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn
from typing import Optional
from functools import lru_cache
from urllib.parse import quote
import os

# Canonical environment names. Every production/local decision must use these helpers.
LIVE_PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})
STAGING_ENVIRONMENTS = frozenset({"staging", "stage"})
PRODUCTION_LIKE_ENVIRONMENTS = LIVE_PRODUCTION_ENVIRONMENTS | STAGING_ENVIRONMENTS
# Explicit local/dev only. Unset, misspellings, and unknown names are not local.
EXPLICIT_DEV_ENVIRONMENTS = frozenset({"development", "local", "dev", "test"})

PRODUCTION_PUBLIC_BASE_URL = "https://evecta.io"
STAGING_PUBLIC_BASE_URL = "https://staging.evecta.io"
LOCAL_PUBLIC_BASE_URL = "http://localhost:8000"


def normalize_environment(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def resolve_environment_name(configured: Optional[str] = None) -> str:
    """Prefer Settings.ENVIRONMENT, then ENVIRONMENT / NODE_ENV process vars."""
    return normalize_environment(
        configured or os.getenv("ENVIRONMENT") or os.getenv("NODE_ENV")
    )


def environment_is_live_production(name: Optional[str]) -> bool:
    return normalize_environment(name) in LIVE_PRODUCTION_ENVIRONMENTS


def environment_is_staging(name: Optional[str]) -> bool:
    return normalize_environment(name) in STAGING_ENVIRONMENTS


def environment_is_production(name: Optional[str]) -> bool:
    """True for live production and staging (cookies, no test-only routes)."""
    return normalize_environment(name) in PRODUCTION_LIKE_ENVIRONMENTS


def environment_allows_dev_only_routes(name: Optional[str]) -> bool:
    """Fail closed: only an explicit local/dev name enables test-only routes."""
    return normalize_environment(name) in EXPLICIT_DEV_ENVIRONMENTS


def environment_cookie_secure(name: Optional[str], request_is_https: bool = False) -> bool:
    """Secure unless explicitly local/dev (then only when the request is HTTPS)."""
    if environment_allows_dev_only_routes(name):
        return bool(request_is_https)
    return True


def environment_public_base_url(name: Optional[str], *, hostname: str = "") -> str:
    """Public origin from the same environment names used for cookies and test routes."""
    if environment_is_live_production(name):
        return PRODUCTION_PUBLIC_BASE_URL
    if environment_is_staging(name):
        return STAGING_PUBLIC_BASE_URL
    if environment_allows_dev_only_routes(name):
        return LOCAL_PUBLIC_BASE_URL
    host = (hostname or "").lower()
    if "evecta.io" in host:
        if "staging" in host:
            return STAGING_PUBLIC_BASE_URL
        return PRODUCTION_PUBLIC_BASE_URL
    return PRODUCTION_PUBLIC_BASE_URL


class Settings(BaseSettings):
    PROJECT_NAME: str = "EVECTA"
    SECRET_KEY: str
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str = "5432"
    DATABASE_URL: Optional[PostgresDsn] = None

    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    REFRESH_TOKEN_EXPIRE_DAYS: int

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_REDIRECT_URI: str
    MAILBOX_GOOGLE_REDIRECT_URI: str

    GOOGLE_MAPS_API_KEY: str
    GEMINI_API_KEY: str
    GEMINI_MODEL: str
    # Optional prepaid Gemini budget (USD) used when no admin budget is set in the dashboard.
    GEMINI_PREPAID_USD: Optional[float] = None
    # Optional: faster/cheaper model for spam-check only (defaults to Flash in spam_checker if unset)
    GEMINI_SPAM_CHECK_MODEL: Optional[str] = None
    # Optional: model for campaign "Generate with AI" drafts (defaults to Flash in llm helper if unset)
    GEMINI_CAMPAIGN_DRAFT_MODEL: Optional[str] = None

    # Per-lead email batch: in-process by default (no Celery worker required locally).
    CAMPAIGN_EMAIL_GENERATION_USE_CELERY: bool = False

    BREVO_API_KEY: str
    BREVO_WEBHOOK_TOKEN: str

    EMAIL_TRACKING_BASE_URL: str
    MAILBOX_SECRET_KEY: str
    # Base URL for unsubscribe links - auto-detected based on environment
    BASE_URL: Optional[str] = None  # Will be auto-detected if not set
    
    # APP_ENVIRONMENT (optional). Unset is treated as non-dev for test-only routes.
    ENVIRONMENT: Optional[str] = None

    # Email settings (for OTP and test emails - MXRoute SMTP)
    # MXRoute SMTP settings:
    # SMTP_HOST: smtp.mxroute.com (or your MXRoute server)
    # SMTP_PORT: 587 (TLS) or 465 (SSL)
    # SMTP_USERNAME: your MXRoute email address
    # SMTP_PASSWORD: your MXRoute email password
    # SMTP_FROM_EMAIL: your MXRoute email address (sender)

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    # Managed Redis (e.g. Upstash) needs AUTH and TLS; both default off so plain
    # local / self-hosted Redis keeps connecting exactly as before.
    REDIS_PASSWORD: Optional[str] = None
    REDIS_SSL: bool = False
    # Mutual TLS (a self-hosted Redis that requires a client certificate): PEM file
    # paths — on Cloud Run, Secret Manager secrets mounted as files. Unset means no
    # client certificate (Upstash) and the system CA store verifies the server.
    REDIS_SSL_CERTFILE: Optional[str] = None
    REDIS_SSL_KEYFILE: Optional[str] = None
    REDIS_SSL_CA_CERTS: Optional[str] = None
    REDIS_URL: Optional[str] = None
    REDIS_RESULT_URL: Optional[str] = None

    SMTP_HOST: str = "smtp.mxroute.com"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    # Inbox for contact form + subscription cancellation feedback (same SMTP as above)
    CONTACT_INBOX_EMAIL: str = "mail@evecta.io"

    HUNTER_API_KEY: str = ""
    # Estimated USD per Hunter credit (Growth plan ≈ $104 / 2,500 searches).
    HUNTER_CREDIT_COST_USD: float = 0.042

    # Lead search source. Keep "google" as the default kill switch until the
    # Overture catalog tables and loader are fully deployed.
    LEAD_SOURCE: str = "google"
    OVERTURE_RELEASE: str = "2026-05-20.0"
    OVERTURE_S3_BASE: str = "s3://overturemaps-us-west-2/release"
    OVERTURE_MIN_CONFIDENCE: float = 0.5
    OVERTURE_AREA_BUFFER_KM: float = 3.0
    OVERTURE_AREA_TTL_DAYS: int = 35
    # Max places cached per (area, category) cold-load. Covers the largest plan
    # (scale = 500 leads_per_search) with headroom for radius-filtering and dedup.
    OVERTURE_CACHE_PER_CATEGORY: int = 1000
    # When a user exhausts a cached area that still has more upstream, top-up pulls
    # the next nearest batch of this many places into the shared cache (§6.11).
    OVERTURE_TOPUP_BATCH: int = 1500

    # Grounded product knowledge (local RAG). The corpus and its index ship with the
    # application; KNOWLEDGE_RAG_ENABLED is the kill switch that returns product
    # questions to the previous ungrounded reply without a rollback.
    KNOWLEDGE_RAG_ENABLED: bool = True
    KNOWLEDGE_EMBEDDING_MODEL: str = "models/gemini-embedding-001"
    # Ceiling on passages sent to the model — the spec's retrieval quality bar is
    # measured at 5, so raising this invalidates the measured floor.
    KNOWLEDGE_TOP_K: int = 5
    # Cosine floor a passage must clear to be used at all. Calibrated by
    # scripts/eval_knowledge_retrieval.py: lower it and recall rises while the
    # "not documented" rate on uncovered questions falls.
    #
    # 0.71 re-measured against app/knowledge/eval/questions.yaml on 2026-08-14 (87
    # labelled questions, 20 controls): recall 0.920, controls abstaining 0.900 —
    # still the lowest floor that clears both bars in the spec. It is deliberately
    # tight: 0.70 gains 1.1 points of recall but drops control abstention to 0.850,
    # under the 0.90 bar, and 0.72 holds abstention at 0.900 while giving up 5.8
    # points of recall. The set now includes terse phrasings observed in live
    # testing; four of them still miss at any threshold that keeps the controls
    # quiet, because gemini-embedding-001 scores short queries below their
    # long-form equivalents. Closing that gap needs query expansion or a reranker,
    # not a lower floor. Do not tune this by feel; gemini-embedding-001 packs related and
    # unrelated text into a narrow band (correct answers here run 0.70-0.82,
    # uncovered questions 0.61-0.75), so a plausible-looking round number is far
    # more destructive than it looks — the previous 0.78 scored recall 0.384, i.e.
    # it discarded the correct passage on nearly two thirds of real questions.
    # Re-run the sweep after any substantial corpus change.
    KNOWLEDGE_MIN_SCORE: float = 0.71
    # The coverage gate for questions already classified as being about the assistant
    # itself ("who are you", "what can you do", "what services do you provide").
    # Softer than the general floor because two independent signals have to agree
    # before it applies: the model flags the turn as about_assistant, AND retrieval
    # still has to clear this bar. For that category the ranking is reliable where the
    # absolute score is not — every phrasing tested put the same product-overview
    # chunk first, scoring 0.69-0.72, so the general floor was splitting one group of
    # questions it consistently gets right, and half of them got the canned
    # one-line reply instead of the answer sitting at position one.
    #
    # It cannot weaken abstention: no control question in the evaluation set is
    # classified this way, so uncovered questions never reach this gate. Measured over
    # 88 questions / 20 controls: recall 0.932 -> 0.955, control abstention unchanged
    # at 0.900, identically at 0.66, 0.65, 0.64 and 0.62.
    #
    # Set to the low end of that range rather than the high end. This category's real
    # scores cluster tightly — "who r u" 0.6571, "who are u" 0.6602, "what do u do"
    # 0.6632, "what services do you provide" 0.6990 — so a gate at 0.66 sat inside the
    # cluster and split it, passing "who are u" by 0.0002 while failing "who r u" by
    # 0.0029. Picking the tightest passing value only pays off when something can leak
    # through a looser one, and here nothing can, so tightness bought no safety and
    # cost robustness against phrasings the evaluation set does not contain.
    KNOWLEDGE_ASSISTANT_MIN_SCORE: float = 0.62
    # How far below the best-scoring chunk a passage may sit and still be sent to the
    # model, once KNOWLEDGE_MIN_SCORE has already judged the question covered. Guards
    # the case where a marginal chunk wins the top slot and the passage that actually
    # answers the question sits just under the floor. Does not affect abstention: the
    # coverage gate is still the top chunk against KNOWLEDGE_MIN_SCORE.
    KNOWLEDGE_NEIGHBOUR_MARGIN: float = 0.05
    # A document not reviewed within this many days is excluded from answers.
    # Effectively disabled: every corpus document carries last_reviewed 2026-08-12,
    # so a 365-day window would have expired the whole corpus on the same day and
    # silently dropped every product question to the "not documented" reply. The
    # field is still required in frontmatter and still recorded per chunk, so
    # lowering this value re-enables the filter without a rebuild.
    KNOWLEDGE_STALE_AFTER_DAYS: int = 36500

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_STARTER_PRICE: str = ""
    STRIPE_GROWTH_PRICE: Optional[str] = None
    STRIPE_SCALE_PRICE: str = ""
    # Optional yearly prices (credits = 12 × monthly plan allowance when interval is year)
    STRIPE_STARTER_ANNUAL_PRICE: Optional[str] = None
    STRIPE_GROWTH_ANNUAL_PRICE: Optional[str] = None
    STRIPE_SCALE_ANNUAL_PRICE: Optional[str] = None
    STRIPE_WEBHOOK_SIGNING_SECRET: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    # Admin accounts are NOT bootstrapped from env (no APP_ADMIN_* secrets).
    # Create/promote via interactive CLI so plaintext never sits in .env or git:
    #   cd backend && python -m scripts.create_admin

    # SES/SNS: comma-separated list of allowed TopicArns e.g. "arn:aws:sns:us-east-1:123:my-topic"
    SNS_ALLOWED_TOPIC_ARNS: str = ""
    # Optional: SES v2 API (recommended for Gmail inbox-hover Unsubscribe on system mail).
    # Region can be inferred from mailbox smtp_host (email-smtp.us-east-1.amazonaws.com).
    AWS_SES_REGION: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    # Optional SES event tracking. Leave unset for campaign mail so SES does not
    # override custom List-Unsubscribe headers (breaks Gmail hover Unsubscribe).
    SES_CONFIGURATION_SET: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore"  # Ignore extra fields from .env that aren't defined in the model
    )

    @property
    def environment_name(self) -> str:
        return resolve_environment_name(self.ENVIRONMENT)

    @property
    def is_live_production(self) -> bool:
        return environment_is_live_production(self.environment_name)

    @property
    def is_staging(self) -> bool:
        return environment_is_staging(self.environment_name)

    @property
    def is_production(self) -> bool:
        """True for production/prod/staging/stage (any capitalization)."""
        return environment_is_production(self.environment_name)

    @property
    def is_local_dev(self) -> bool:
        """Explicit local/dev only — OTP logging and other fail-open local tooling."""
        return environment_allows_dev_only_routes(self.environment_name)

    @property
    def allows_dev_only_routes(self) -> bool:
        """Same predicate as is_local_dev: unset/unknown names never enable test endpoints."""
        return self.is_local_dev

    def model_post_init(self, __context):
        import logging
        _logger = logging.getLogger(__name__)

        self._validate_redis_tls_files()

        # Auto-build Redis URL if not explicitly provided
        if not self.REDIS_URL:
            self.REDIS_URL = self.redis_cache_url

        # Warn at startup about empty critical config values
        _critical = {
            "STRIPE_SECRET_KEY": self.STRIPE_SECRET_KEY,
            "STRIPE_WEBHOOK_SIGNING_SECRET": self.STRIPE_WEBHOOK_SIGNING_SECRET,
            "SMTP_USERNAME": self.SMTP_USERNAME,
            "SMTP_PASSWORD": self.SMTP_PASSWORD,
            "SMTP_FROM_EMAIL": self.SMTP_FROM_EMAIL,
            "GOOGLE_MAPS_API_KEY": self.GOOGLE_MAPS_API_KEY,
            "GEMINI_API_KEY": self.GEMINI_API_KEY,
        }
        for key, value in _critical.items():
            if not value:
                _logger.warning("Config: APP_%s is empty — related features will not work", key)

        # Enforce minimum SECRET_KEY length — short keys can be brute-forced offline
        if len(self.SECRET_KEY) < 32:
            raise ValueError(
                "APP_SECRET_KEY must be at least 32 characters. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    @property
    def async_database_url(self) -> str:
        """
        Returns a valid async SQLModel-compatible PostgreSQL URL.
        Example: postgresql+asyncpg://user:password@localhost:5432/dbname
        """
        if self.DATABASE_URL:
            return str(self.DATABASE_URL)
        if self.POSTGRES_HOST.startswith("/"):
            # Unix socket directory, e.g. Cloud Run's /cloudsql/PROJECT:REGION:INSTANCE.
            # The path cannot sit in the netloc, so pass it as ?host=; asyncpg and
            # libpq both connect to <dir>/.s.PGSQL.5432.
            return (
                f"postgresql+asyncpg://{quote(self.POSTGRES_USER, safe='')}"
                f":{quote(self.POSTGRES_PASSWORD, safe='')}"
                f"@/{self.POSTGRES_DB}?host={self.POSTGRES_HOST}"
            )
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def psycopg_database_url(self) -> str:
        """
        libpq/psycopg-compatible URL for the LangGraph Postgres checkpointer.
        The checkpointer uses psycopg (v3), not asyncpg, so strip the SQLAlchemy
        '+asyncpg' driver suffix from the async URL.
        Example: postgresql://user:password@localhost:5432/dbname
        """
        return self.async_database_url.replace("+asyncpg", "")

    @property
    def redis_cache_url(self) -> str:
        """
        Redis URL for the app's own clients (cache, auth state, rate limiter),
        built from REDIS_HOST/PORT/DB plus optional REDIS_PASSWORD / REDIS_SSL.
        Example: rediss://:password@host.upstash.io:6379/0
        """
        scheme = "rediss" if self.REDIS_SSL else "redis"
        auth = f":{quote(self.REDIS_PASSWORD, safe='')}@" if self.REDIS_PASSWORD else ""
        return f"{scheme}://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def redis_ssl_options(self) -> dict:
        """
        Client certificate / CA options shared by every Redis client: redis-py,
        Kombu (broker), the Celery result backend and the rate limiter. Empty unless
        mutual TLS is configured, so existing setups connect exactly as before.
        """
        options = {
            "ssl_certfile": self.REDIS_SSL_CERTFILE,
            "ssl_keyfile": self.REDIS_SSL_KEYFILE,
            "ssl_ca_certs": self.REDIS_SSL_CA_CERTS,
        }
        return {k: v for k, v in options.items() if v}

    def _validate_redis_tls_files(self) -> None:
        """Fail at startup, with the variable name, instead of on the first Redis call."""
        if bool(self.REDIS_SSL_CERTFILE) != bool(self.REDIS_SSL_KEYFILE):
            raise ValueError("APP_REDIS_SSL_CERTFILE and APP_REDIS_SSL_KEYFILE must be set together")
        files = {
            "APP_REDIS_SSL_CERTFILE": self.REDIS_SSL_CERTFILE,
            "APP_REDIS_SSL_KEYFILE": self.REDIS_SSL_KEYFILE,
            "APP_REDIS_SSL_CA_CERTS": self.REDIS_SSL_CA_CERTS,
        }
        files = {name: path for name, path in files.items() if path}
        if files and not self.REDIS_SSL:
            raise ValueError(f"{', '.join(files)} set but APP_REDIS_SSL is false (TLS is required)")
        for name, path in files.items():
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                raise ValueError(f"{name}={path} is not a readable file")

    def get_base_url(self) -> str:
        """
        Automatically detects and returns the correct BASE_URL based on environment.
        Priority:
        1. Explicitly set APP_BASE_URL in .env
        2. Environment variable ENVIRONMENT or NODE_ENV
        3. Auto-detect from hostname (if running in production/staging)
        4. Explicit local/dev → localhost; otherwise fail closed to production
        """
        if self.BASE_URL:
            return self.BASE_URL

        hostname = os.getenv("HOSTNAME", "") or ""
        try:
            import socket
            hostname = f"{socket.gethostname()} {hostname}".strip()
        except OSError:
            pass
        return environment_public_base_url(self.environment_name, hostname=hostname)

    def get_unsubscribe_base_url(self) -> str:
        """
        Returns the base URL for constructing unsubscribe links in emails.

        Uses EMAIL_TRACKING_BASE_URL as the domain — it is a required field so it is
        always set correctly on every server (staging, production, local).

        On staging/production, nginx strips /api/ before forwarding to FastAPI, so
        the public URL must include /api. On local, FastAPI is accessed directly so
        no /api prefix is needed.
        """
        base = self.EMAIL_TRACKING_BASE_URL.rstrip("/")
        is_local = "localhost" in base or "127.0.0.1" in base
        prefix = "" if is_local else "/api"
        return f"{base}{prefix}/v1/unsubscribe"

@lru_cache()
def get_settings() -> Settings:
    """ Load settings once and cache globally."""
    return Settings()

    
