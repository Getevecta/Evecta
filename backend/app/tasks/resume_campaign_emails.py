from app.core.celery_app import celery_app
import asyncio
import logging

logger = logging.getLogger(__name__)

_RESUME_LOCK_KEY = "lock:resume_stalled_campaign_emails"
_RESUME_LOCK_TTL = 55


def _try_acquire_resume_lock() -> bool:
    """True if this beat tick should scan; fail-open when Redis is down."""
    from app.utils.redis_context import REDIS_AVAILABLE, redis_client

    if not (REDIS_AVAILABLE and redis_client):
        return True
    try:
        return bool(redis_client.set(_RESUME_LOCK_KEY, "1", nx=True, ex=_RESUME_LOCK_TTL))
    except Exception as exc:
        logger.warning("Resume-stalled lock acquire failed, continuing: %s", exc)
        return True


def _release_resume_lock() -> None:
    from app.utils.redis_context import REDIS_AVAILABLE, redis_client

    if not (REDIS_AVAILABLE and redis_client):
        return
    try:
        redis_client.delete(_RESUME_LOCK_KEY)
    except Exception as exc:
        logger.warning("Resume-stalled lock release failed: %s", exc)


@celery_app.task(name="app.tasks.resume_campaign_emails.resume_stalled_campaign_email_generations")
def resume_stalled_campaign_email_generations_task():
    """Periodic self-heal for abandoned campaign email generation runs."""
    if not _try_acquire_resume_lock():
        logger.info("[RESUME_STALLED_CAMPAIGN_EMAILS] Skipped — lock held")
        return {"skipped": True, "reason": "lock_held"}

    from app.core.celery_helper import cleanup_event_loop, get_celery_session_factory
    from app.services.campaign_email_generation_service import (
        resume_stalled_campaign_email_generations,
    )

    session_factory, task_engine = get_celery_session_factory()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            resume_stalled_campaign_email_generations(session_factory)
        )
        logger.info("[RESUME_STALLED_CAMPAIGN_EMAILS] Completed: %s", result)
        return result
    except Exception as exc:
        logger.error(
            "[RESUME_STALLED_CAMPAIGN_EMAILS] Failed: %s",
            exc,
            exc_info=True,
        )
        return {"candidates": 0, "resumed": 0, "skipped": 0, "errors": 1, "error": str(exc)}
    finally:
        cleanup_event_loop(loop, task_engine)
        _release_resume_lock()
