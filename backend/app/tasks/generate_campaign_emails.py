from app.core.celery_app import celery_app
import asyncio
import logging

logger = logging.getLogger(__name__)

_DEFAULT_CHUNK = 25


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=20,
    retry_backoff_max=120,
    retry_jitter=True,
    acks_late=True,
    reject_on_worker_lost=True,
)
def generate_campaign_emails_task(
    self,
    campaign_id: str,
    user_id: str,
    regenerate_all: bool = False,
    start_index: int = 0,
    count: int = _DEFAULT_CHUNK,
):
    """
    Background task: generate one chunk of per-lead emails.
    Crashes re-queue the chunk (acks_late); READY rows are never reset.
    """
    logger.info(
        "[GENERATE_CAMPAIGN_EMAILS] Starting campaign_id=%s task_id=%s start=%s count=%s",
        campaign_id,
        self.request.id,
        start_index,
        count,
    )

    from app.core.celery_helper import cleanup_event_loop, get_celery_session_factory
    from app.services.campaign_email_generation_service import generate_pending_campaign_emails

    session_factory, task_engine = get_celery_session_factory()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(
            generate_pending_campaign_emails(
                campaign_id,
                user_id,
                session_factory,
                regenerate_all=regenerate_all,
                start_index=start_index,
                count=count,
            )
        )
        logger.info(
            "[GENERATE_CAMPAIGN_EMAILS] Completed campaign_id=%s start=%s",
            campaign_id,
            start_index,
        )
    except Exception as exc:
        logger.error(
            "[GENERATE_CAMPAIGN_EMAILS] Failed campaign_id=%s start=%s: %s",
            campaign_id,
            start_index,
            exc,
            exc_info=True,
        )
        raise
    finally:
        cleanup_event_loop(loop, task_engine)
