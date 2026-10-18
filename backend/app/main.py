import logging
import sys
import asyncio

# psycopg (the LangGraph Postgres checkpointer) needs the Selector event loop on
# Windows — the default Proactor loop raises "cannot use ProactorEventLoop". Playwright
# scraping runs in the Celery workers (separate process), so the API event loop can
# safely use Selector. No-op on Linux/production.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi import HTTPException
from app.core.config import get_settings
from app.utils.http_errors import http_exception_sanitizer, unhandled_exception_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)
from contextlib import asynccontextmanager
from app.core.redis import init_redis, close_redis
from app.core.http_client import init_http_client, close_http_client
from app.core.scheduler import reply_fetcher_loop
import asyncio
from app.database.session import check_connection
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.limiter import limiter
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from app.services.chat_graph import build_chat_graph
from app.api.v1.google_auth import router as google_auth_router
from app.api.v1.auth import router as auth_router
from app.api.v1.role import router as role_router
from app.api.v1.user import router as user_router
from app.api.v1.otp import router as otp_router
from app.api.v1.chat import router as chat_router
from app.api.v1.lead import router as lead_router
from app.api.v1.billing import router as billing_router
from app.api.v1.campaign import router as campaign_router
from app.api.v1.campaign_category import router as campaign_category_router
from app.api.v1.campaign_goal import router as campaign_goal_router
from app.api.v1.campaign_lead import router as campaign_lead_router
from app.api.v1.campaign_draft import router as campaign_draft_router
from app.api.v1.campaign_launch import router as campaign_launch_router
from app.api.v1.campaign_preview import router as campaign_preview_router
from app.api.v1.campaign_emails import router as campaign_emails_router
from app.api.v1.campaign_personalization import router as personalization_router, campaign_router as campaign_personalization_router
from app.api.v1.email_template import router as email_template_router
from app.api.v1.campaign_insight import router as campaign_insight_router
from app.api.v1.company import router as company_router
from app.api.v1.email_replies import router as email_replies_router
from app.api.v1.domain import router as domain_router
from app.api.v1.mailbox import router as mailbox_router
from app.api.v1.inbox import router as inbox_router
from app.api.v1.unsubscribe import router as unsubscribe_router
from app.api.v1.system_domain import router as system_domain_router
from app.api.v1.system_mailbox import router as system_mailbox_router
from app.api.v1.webhook_ses import router as ses_webhook_router
from app.api.v1.email_insight import router as email_insight_router
from app.api.v1.contact import router as contact_router
from app.api.v1.ai_usage import router as ai_usage_router
from app.api.v1.admin_credits import router as admin_credits_router
from app.api.v1.gemini_purchases import router as gemini_purchases_router
from app.api.v1.external_api_usage import router as external_api_usage_router
from app.api.v1.chat_memory import router as chat_memory_router


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    logger.info("Redis connected")
    await init_http_client()

    success = await check_connection()
    if success:
        logger.info("Database connection successful")
        asyncio.create_task(reply_fetcher_loop())
        try:
            from app.database.session import async_session_factory
            # Ensures admin/user roles only — does not create credentials from env.
            # Create an admin with: python -m scripts.create_admin
            from app.services.admin_bootstrap import ensure_admin_user

            async with async_session_factory() as session:
                await ensure_admin_user(session)
        except Exception:
            logger.warning("Admin role bootstrap failed", exc_info=True)
    else:
        logger.error("Database connection failed")

    # Chat graph + checkpointer. The graph is ALWAYS built so the chat route never has
    # to fall back to a Redis path: a durable Postgres checkpointer when the event loop
    # allows it, otherwise an in-memory checkpointer (same semantics as the old in-memory
    # fallback — works in-process, lost on restart). Conversation state lives in the
    # graph state either way.
    app.state.chat_graph = None
    app.state._chat_checkpointer_pool = None
    _loop_name = type(asyncio.get_running_loop()).__name__.lower()
    if "proactor" in _loop_name:
        # psycopg async cannot use the Windows Proactor loop. Use the in-memory
        # checkpointer (avoids a 30s connection hang + log spam). Start the API with
        # `python run.py` to get the Selector loop + durable history locally. Production
        # (Linux) is unaffected.
        logger.warning(
            "Postgres checkpointer SKIPPED — Windows Proactor event loop is incompatible "
            "with psycopg async; using in-memory checkpointer (no durable history). For "
            "local durable history run `python run.py` (Selector loop)."
        )
        app.state.chat_graph = build_chat_graph(MemorySaver())
    else:
        try:
            pool = AsyncConnectionPool(
                conninfo=settings.psycopg_database_url,
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
            )
            await pool.open()
            checkpointer = AsyncPostgresSaver(pool)
            await checkpointer.setup()
            app.state._chat_checkpointer_pool = pool
            app.state.chat_graph = build_chat_graph(checkpointer)
            logger.info("Chat checkpointer + graph ready (durable conversation history)")
        except Exception:
            logger.exception("Postgres checkpointer init failed — falling back to in-memory checkpointer")
            app.state.chat_graph = build_chat_graph(MemorySaver())

    yield

    pool = getattr(app.state, "_chat_checkpointer_pool", None)
    if pool is not None:
        try:
            await pool.close()
            logger.info("Chat checkpointer pool closed")
        except Exception:
            logger.exception("Error closing chat checkpointer pool")

    await close_http_client()
    await close_redis()
    logger.info("Redis connection closed")


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(HTTPException, http_exception_sanitizer)
app.add_exception_handler(Exception, unhandled_exception_handler)
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def security_headers_middleware(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # React/Vite dev server
        "https://staging.evecta.io",
        "https://substaging.evecta.io",
        "https://evecta.io",
    "https://www.evecta.io",
    ],  # Production frontend
    allow_credentials=True,  # needed for cookies (refresh_token)
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(role_router)
app.include_router(user_router)
app.include_router(google_auth_router)
app.include_router(otp_router)
app.include_router(chat_router)
app.include_router(chat_memory_router)
app.include_router(lead_router)
app.include_router(campaign_router)
app.include_router(campaign_category_router)
app.include_router(campaign_goal_router)
app.include_router(campaign_lead_router)
app.include_router(campaign_draft_router)
app.include_router(campaign_launch_router)
app.include_router(campaign_preview_router)
app.include_router(campaign_emails_router)
app.include_router(personalization_router)
app.include_router(campaign_personalization_router)
app.include_router(email_template_router)
app.include_router(campaign_insight_router)
app.include_router(company_router)
app.include_router(email_replies_router)
app.include_router(domain_router)
app.include_router(mailbox_router)
app.include_router(inbox_router)
app.include_router(unsubscribe_router)
app.include_router(system_domain_router)
app.include_router(system_mailbox_router)
app.include_router(ses_webhook_router)
app.include_router(email_insight_router)
app.include_router(billing_router)
app.include_router(admin_credits_router)
app.include_router(gemini_purchases_router)
app.include_router(external_api_usage_router)
app.include_router(contact_router)
app.include_router(ai_usage_router)

@app.get("/")
async def root():
    """Root endpoint returning a welcome message."""
    return {
        "status": "success",
        "project": settings.PROJECT_NAME,
    }


@app.get("/health", tags=["System"])
async def health():
    """Liveness check — returns 200 if the process is running."""
    return {"status": "ok"}


@app.get("/ready", tags=["System"])
async def ready():
    """Readiness check — verifies DB and Redis are reachable."""
    from fastapi import HTTPException
    from app.core.redis import get_redis

    errors = {}

    # Check database
    db_ok = await check_connection()
    if not db_ok:
        errors["database"] = "unreachable"

    # Check Redis
    try:
        redis = get_redis()
        await redis.ping()
    except Exception:
        errors["redis"] = "unreachable"

    if errors:
        raise HTTPException(status_code=503, detail={"status": "not ready", "errors": errors})

    return {"status": "ready"}