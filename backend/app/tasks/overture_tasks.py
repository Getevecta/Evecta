from app.core.celery_app import celery_app
import asyncio
import logging

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2},
    retry_backoff=30,
    retry_backoff_max=180,
    retry_jitter=True,
)
def load_overture_area_task(self, industry, location, search_radius_km, search_terms, user_id=None):
    """
    Background cold-load of an Overture (area, category) into overture_places.

    Runs off the request path so a slow S3 pull (30s–several minutes) never blocks
    a chat request. Once it finishes, the area is warm and the user's retry is fast.

    Follows the same isolation pattern as enrich_leads_task: fresh engine + event loop.
    """
    logger.info(
        "[OVERTURE_LOAD] Starting background load | industry=%s location=%s radius_km=%s task_id=%s",
        industry, location, search_radius_km, self.request.id,
    )

    from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop
    from app.services.lead_generation_service import load_overture_area_background

    session_factory, task_engine = get_celery_session_factory()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(
            load_overture_area_background(
                industry=industry,
                location=location,
                search_radius_km=search_radius_km,
                search_terms=search_terms,
                session_factory=session_factory,
                user_id=user_id,
            )
        )
        logger.info("[OVERTURE_LOAD] Background load complete | location=%s industry=%s", location, industry)
    except Exception as e:
        logger.error(
            "[OVERTURE_LOAD] Background load failed | location=%s industry=%s: %s",
            location, industry, str(e), exc_info=True,
        )
        raise
    finally:
        cleanup_event_loop(loop, task_engine)


@celery_app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1},
    retry_backoff=30,
    retry_backoff_max=90,
    retry_jitter=True,
)
def load_and_fill_overture_task(self, log_id, user_id, industry, location, search_radius_km, search_terms, limit, city_for_tier=None, topup=False):
    """
    Cold-load an Overture area, then SAVE its leads into an existing (empty) LeadLog.

    The chat request created the LeadLog and returned its id; the frontend is already
    polling that log. This task fills it so the leads appear in the table automatically
    — no re-search. Then it enqueues enrichment, exactly like the synchronous flow.

    topup=True (§6.11): the area is already cached but the user drained it; pull the
    next nearest batch from Overture into the shared cache first, then fill.
    """
    logger.info(
        "[OVERTURE_FILL] Starting load+fill | log_id=%s industry=%s location=%s task_id=%s",
        log_id, industry, location, self.request.id,
    )

    from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop

    session_factory, task_engine = get_celery_session_factory()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        saved = loop.run_until_complete(
            _fill_overture_lead_log(
                log_id, user_id, industry, location, search_radius_km, search_terms, limit, session_factory,
                city_for_tier=city_for_tier, topup=topup,
            )
        )
        if saved > 0:
            from app.tasks.enrich_leads import enrich_leads_task
            enrich_leads_task.delay(log_id)
            logger.info("[OVERTURE_FILL] Filled %s leads + enqueued enrichment | log_id=%s", saved, log_id)
        else:
            logger.info("[OVERTURE_FILL] No leads for area | log_id=%s", log_id)
    except Exception as e:
        logger.error("[OVERTURE_FILL] Load+fill failed | log_id=%s: %s", log_id, str(e), exc_info=True)
        # Mark the log failed (fresh session) so the frontend stops polling and shows an
        # error instead of an endless "gathering" spinner.
        try:
            loop.run_until_complete(_mark_lead_log_status(log_id, "failed", session_factory))
        except Exception:
            logger.error("[OVERTURE_FILL] Could not mark log failed | log_id=%s", log_id, exc_info=True)
        raise
    finally:
        cleanup_event_loop(loop, task_engine)


async def _mark_lead_log_status(log_id, status: str, session_factory) -> None:
    """Set a LeadLog's status in a fresh session (used to mark 'failed' after a crash)."""
    from uuid import UUID
    from sqlalchemy import text
    async with session_factory() as db:
        await db.execute(
            text("UPDATE lead_logs SET status = :s WHERE id = :id"),
            {"s": status, "id": UUID(str(log_id))},
        )
        await db.commit()


@celery_app.task(bind=True)
def overture_refresh_task(self):
    """Monthly: re-pull every cached Overture area from the latest release (in place)."""
    logger.info("[OVERTURE_REFRESH] Task started | task_id=%s", self.request.id)

    from app.core.celery_helper import get_celery_session_factory, cleanup_event_loop
    from app.services.overture_refresh_service import refresh_overture_areas

    session_factory, task_engine = get_celery_session_factory()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(refresh_overture_areas(session_factory))
        logger.info("[OVERTURE_REFRESH] Task complete | %s", result)
    except Exception as e:
        logger.error("[OVERTURE_REFRESH] Task failed: %s", str(e), exc_info=True)
        raise
    finally:
        cleanup_event_loop(loop, task_engine)


async def _fill_overture_lead_log(
    log_id, user_id, industry, location, search_radius_km, search_terms, limit, session_factory,
    city_for_tier=None, topup=False,
) -> int:
    """Cold-load (or top-up) the area, query its leads, and insert them under the log."""
    from datetime import datetime, timezone
    from uuid import UUID
    from sqlalchemy import insert, text
    from app.models.lead_log_lead import LeadLogLead
    from app.services.lead_generation_service import get_leads_overture

    log_uuid = UUID(str(log_id))
    async with session_factory() as db:
        # Idempotency guard: if this log was already filled (e.g. the task is being
        # retried after a post-save failure), do NOT re-insert leads or re-charge
        # credits. Return the existing count so enrichment is still (re-)enqueued.
        existing = (
            await db.execute(
                text("SELECT COUNT(*) FROM lead_log_leads WHERE lead_log_id = :id"),
                {"id": log_uuid},
            )
        ).scalar() or 0
        if existing > 0:
            logger.info("[OVERTURE_FILL] Log already has %s leads — skipping fill | log_id=%s", existing, log_id)
            return int(existing)

        # load_if_cold=True → cold-load the area (this is the slow part), then query.
        # Same geographic-precision + fresh-leads behavior as the synchronous path
        # (city-dominant + spillover in Mode A; exclude this user's already-seen).
        leads, _error_info = await get_leads_overture(
            industry, location, search_radius_km, limit, search_terms,
            db=db, load_if_cold=True,
            city_for_tier=city_for_tier,
            user_id=user_id,
            topup=topup,
        )
        if not leads:
            # Load finished with no leads → mark the log so the frontend stops polling
            # and shows "no results" instead of spinning on an empty gathering log forever.
            await db.execute(
                text("UPDATE lead_logs SET status = 'empty' WHERE id = :id"),
                {"id": log_uuid},
            )
            await db.commit()
            return 0

        now = datetime.now(timezone.utc)
        lead_rows = [
            {
                "business_name": (lead.get("business_name") or "")[:255],
                "industry": (lead.get("industry") or "")[:255],
                # Use the Overture-provided email if present; otherwise enrichment scrapes it.
                "email": (lead.get("email") or None),
                "contact_number": (lead.get("contact_number") or "")[:255],
                "address": (lead.get("address") or "")[:255],
                "website": (lead.get("website") or "")[:255],
                "lead_score": 0,
                "enrichment_status": "processing",
                # Master-catalog link (overture_places.overture_id); NULL for
                # non-Overture leads.
                "overture_id": (str(lead.get("overture_id"))[:64] if lead.get("overture_id") else None),
                "lead_log_id": log_uuid,
                "created_at": now,
                "updated_at": now,
            }
            for lead in leads
        ]
        for start in range(0, len(lead_rows), 250):
            await db.execute(insert(LeadLogLead).values(lead_rows[start:start + 250]))
        # Leads saved → the log is no longer "gathering".
        await db.execute(
            text("UPDATE lead_logs SET status = 'active' WHERE id = :id"),
            {"id": log_uuid},
        )
        await db.commit()

        # Deduct credits now that leads are actually saved (1 per lead).
        try:
            from app.services.credit_service import spend_credits
            await spend_credits(
                db, UUID(str(user_id)), "lead_found",
                quantity=len(lead_rows),
                description=f"Overture: {industry} in {location}",
            )
        except Exception:
            logger.error("[OVERTURE_FILL] Credit deduction failed | log_id=%s", log_id, exc_info=True)

        return len(lead_rows)
