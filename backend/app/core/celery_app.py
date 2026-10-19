from celery import Celery
from celery.schedules import crontab
from app.core.config import get_settings
from app.utils.log_redaction import redact_url_credentials
import logging
import ssl

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "evecta",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_RESULT_URL,
)

# Recommended Celery config
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # IMPORTANT for long-running jobs and concurrent task execution
    worker_prefetch_multiplier=1,  # Do NOT prefetch - wait for task completion before fetching next
    task_acks_late=True,           # ACK after task completes, not before
    task_reject_on_worker_lost=True, # Reject task if worker dies
    broker_connection_retry_on_startup=True,
    
    # Better concurrency handling
    task_track_started=True,        # Track when task starts
    task_max_retries=3,             # Max retries for failed tasks
    task_default_retry_delay=10,    # Base delay; tasks should use retry_backoff + retry_jitter
    
    # Connection pooling
    broker_pool_limit=10,           # Redis connection pool size
    broker_connection_max_retries=3,

)

def redis_tls_options(url, cfg=settings):
    """TLS settings for a Celery Redis URL, or None for plain redis://.

    Always verifies the server certificate — without this kombu silently falls back
    to CERT_NONE for the broker and the result backend refuses to start — and adds
    the client certificate when mutual TLS is configured. Plain redis:// rejects ssl
    options, so they are only applied to rediss:// URLs.
    """
    if not (url or "").startswith("rediss://"):
        return None
    return {"ssl_cert_reqs": ssl.CERT_REQUIRED, **cfg.redis_ssl_options}


_broker_tls = redis_tls_options(settings.REDIS_URL)
if _broker_tls:
    celery_app.conf.broker_use_ssl = _broker_tls
_backend_tls = redis_tls_options(settings.REDIS_RESULT_URL)
if _backend_tls:
    celery_app.conf.redis_backend_use_ssl = _backend_tls

celery_app.conf.beat_schedule = {
    "dispatch-email-jobs-every-60s": {
        "task": "app.tasks.email_dispatcher.dispatch_due_jobs",
        "schedule": 60.0,
    },
    "resume-stalled-campaign-emails-every-60s": {
        "task": "app.tasks.resume_campaign_emails.resume_stalled_campaign_email_generations",
        "schedule": 60.0,
    },
    # Monthly: refresh cached Overture areas from the latest release (1st @ 03:00 UTC).
    "overture-monthly-refresh": {
        "task": "app.tasks.overture_tasks.overture_refresh_task",
        "schedule": crontab(day_of_month=1, hour=3, minute=0),
    },
}

logger.info("Celery app configured with settings:")
logger.info("  Broker: %s", redact_url_credentials(settings.REDIS_URL))
logger.info("  Result Backend: %s", redact_url_credentials(settings.REDIS_RESULT_URL))
logger.info(f"  Task ACK: late")
logger.info(f"  Prefetch Multiplier: 1 (concurrent task support)")

# for tasks auto-discovery the import is necessary otherwise tasks won't be registered
import app.tasks.enrich_leads
import app.tasks.email_dispatcher
import app.tasks.mail_job
import app.tasks.generate_campaign_emails
import app.tasks.resume_campaign_emails
import app.tasks.overture_tasks