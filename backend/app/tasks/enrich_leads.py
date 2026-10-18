from app.core.celery_app import celery_app
from app.services.lead_generation_service import enrich_leads_background
import asyncio
import logging

logger = logging.getLogger(__name__)
#enrich_leads.py
@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=15,
    retry_backoff_max=90,
    retry_jitter=True,
)
def enrich_leads_task(self, lead_log_id):
    """
    Background task to enrich leads with email addresses and scoring.
    
    ✅ Creates fresh event loop
    ✅ Creates fresh engine (isolated from other tasks)
    ✅ Properly disposes engine before closing loop
    """
    logger.info("=" * 80)
    logger.info(f"🔄 [ENRICH_LEADS] Starting enrichment task for lead_log_id={lead_log_id}, task_id={self.request.id}")
    logger.info("=" * 80)
    
    # STEP 1: Create fresh engine + session factory for THIS task only
    from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop
    session_factory, task_engine = get_celery_session_factory()
    logger.info("[ENRICH_LEADS] ✅ Created fresh engine for this task")
    
    # STEP 2: Create fresh event loop for THIS task only
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    logger.info("[ENRICH_LEADS] ✅ Created fresh event loop for this task")

    try:
        logger.info(f"[ENRICH_LEADS] 📊 Enriching leads for lead_log_id={lead_log_id}")
        
        loop.run_until_complete(
            enrich_leads_background(
                lead_log_id,
                session_factory=session_factory,
            )
        )
        
        logger.info(f"[ENRICH_LEADS] ✅ Enrichment completed for lead_log_id={lead_log_id}")
        
    except Exception as e:
        logger.error(f"[ENRICH_LEADS] ❌ Enrichment failed for lead_log_id={lead_log_id}: {str(e)}", exc_info=True)
        raise  # Re-raise to trigger Celery retry mechanism
        
    finally:
        # STEP 3: Clean up properly (using helper function)
        logger.info("[ENRICH_LEADS] 🧹 Cleaning up...")
        cleanup_event_loop(loop, task_engine)
        logger.info("=" * 80)
        logger.info("[ENRICH_LEADS] ✨ Enrichment task cleanup complete")
        logger.info("=" * 80)