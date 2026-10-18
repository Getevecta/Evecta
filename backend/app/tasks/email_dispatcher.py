# app/tasks/email_dispatcher.py

from app.core.celery_app import celery_app
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select, update, func
from app.models.email_job import EmailJob, EmailJobStatus
from app.models.user import User
from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop
from app.core.email_limits import SEND_STAGGER_SECONDS

logger = logging.getLogger(__name__)

DISPATCH_BATCH = 20


async def _dispatch_due_jobs(session_factory):
    """
    Internal async function to dispatch due jobs.
    Takes session_factory as parameter (now task-specific).
    """
    now = datetime.now(timezone.utc)
    logger.info("[DISPATCH] Starting dispatch_due_jobs")

    async with session_factory() as db:
        # Use explicit transaction
        async with db.begin():
            # Select jobs directly that are QUEUED and due
            logger.info("[DISPATCH] Querying for due jobs...")
            jobs = (await db.scalars(
                select(EmailJob)
                .join(User, User.id == EmailJob.user_id)
                .where(
                    EmailJob.status == EmailJobStatus.QUEUED,
                    EmailJob.scheduled_for <= now,
                )
                .order_by(
                    func.coalesce(
                        User.last_queue_served_at,
                        datetime(1970, 1, 1, tzinfo=timezone.utc)
                    ).asc(),
                    EmailJob.scheduled_for.asc(),
                )
                .limit(DISPATCH_BATCH)
            )).all()

            if not jobs:
                logger.info("[DISPATCH] No jobs to dispatch")
                return {"dispatched": 0, "users": 0}

            logger.info(f"[DISPATCH] Found {len(jobs)} jobs to process")
            dispatched = 0
            processed_user_ids = set()
            jobs_to_dispatch = []
            user_updates = []

            for job in jobs:
                # Try to atomically mark job as SENDING
                result = await db.execute(
                    update(EmailJob)
                    .where(
                        EmailJob.id == job.id,
                        EmailJob.status == EmailJobStatus.QUEUED,
                    )
                    .values(
                        status=EmailJobStatus.SENDING,
                        attempts=EmailJob.attempts + 1,
                        updated_at=now,
                    )
                )

                # Only proceed if we successfully updated the row
                if result.rowcount == 0:
                    logger.info(f"[DISPATCH] Failed to mark job {job.id} as SENDING - already claimed")
                    continue

                # Collect for batch processing
                jobs_to_dispatch.append(job)
                user_updates.append(job.user_id)
                dispatched += 1
                processed_user_ids.add(job.user_id)
                logger.info(f"[DISPATCH] ✅ Marked job {job.id} as SENDING for user {job.user_id}")

            # Batch update user's last served time
            if user_updates:
                logger.info(f"[DISPATCH] Updating last_queue_served_at for {len(user_updates)} users")
                await db.execute(
                    update(User)
                    .where(User.id.in_(user_updates))
                    .values(last_queue_served_at=now)
                )

        # ✅ Transaction committed here before sending tasks

        # Space each user's sends by SEND_STAGGER_SECONDS so SMTP is not burst
        user_countdown: dict = {}
        for job in jobs_to_dispatch:
            delay = user_countdown.get(job.user_id, 0)
            logger.info(
                f"[DISPATCH] 📧 Sending task for job {job.id} (countdown={delay}s)"
            )
            celery_app.send_task(
                "app.tasks.mail_job.process_email_job",
                args=[str(job.id)],
                countdown=delay,
            )
            user_countdown[job.user_id] = delay + SEND_STAGGER_SECONDS

        logger.info(f"[DISPATCH] 🎉 Dispatched {dispatched} jobs across {len(processed_user_ids)} users")
        return {"dispatched": dispatched, "users": len(processed_user_ids)}


@celery_app.task(name="app.tasks.email_dispatcher.dispatch_due_jobs")
def dispatch_due_jobs():
    """
    Dispatch due emails with proper event loop and engine management.
    
    ✅ Creates fresh event loop
    ✅ Creates fresh engine (isolated from other tasks)
    ✅ Properly disposes engine before closing loop
    ✅ Cancels pending tasks before closing loop
    
    This runs every 30 seconds (per beat schedule)
    """
    logger.info("=" * 80)
    logger.info("🔄 [EMAIL_DISPATCHER] Starting email dispatch job")
    logger.info("=" * 80)
    
    # STEP 1: Create fresh engine + session factory for THIS task only
    session_factory, task_engine = get_celery_session_factory()
    logger.info("[EMAIL_DISPATCHER] ✅ Created fresh engine for this task")
    
    # STEP 2: Create fresh event loop for THIS task only
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("[EMAIL_DISPATCHER] ✅ Created fresh event loop for this task")

    try:
        logger.info("[EMAIL_DISPATCHER] 📧 Starting to dispatch due emails...")
        result = loop.run_until_complete(_dispatch_due_jobs(session_factory))
        logger.info(f"[EMAIL_DISPATCHER] ✅ Dispatch completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"[EMAIL_DISPATCHER] ❌ Email dispatch failed: {str(e)}", exc_info=True)
        # Don't re-raise for beat tasks - just log it
        return {"dispatched": 0, "users": 0, "error": str(e)}
        
    finally:
        # STEP 3: Clean up properly (using helper function)
        logger.info("[EMAIL_DISPATCHER] 🧹 Cleaning up...")
        cleanup_event_loop(loop, task_engine)
        logger.info("=" * 80)
        logger.info("[EMAIL_DISPATCHER] ✨ Email dispatch task cleanup complete")
        logger.info("=" * 80)