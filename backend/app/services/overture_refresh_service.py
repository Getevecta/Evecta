"""
Monthly Overture refresh.

Re-pulls every cached (area, category) from the latest Overture release and upserts
it into overture_places IN PLACE — so map data stays current without wiping enrichment
or breaking saved leads. Also re-seeds the category taxonomy.

Safety rules (see OVERTURE_LEAD_GENERATION.md):
- Upsert in place (ON CONFLICT overture_id DO UPDATE) — ids stay stable.
- Overture fields only — never overwrite enrichment columns (when they exist).
- Don't delete vanished places — upsert never deletes.
- Skip non-Overture rows — `_persist_overture_rows` only writes source='overture'.
"""

import asyncio
import logging

from sqlalchemy import text

from app.core.config import get_settings
from app.services.lead_generation_service import (
    _fetch_overture_area_rows,
    _persist_overture_rows,
    _overture_s3_path,
)
from app.services.overture_category_service import seed_overture_categories_from_csv

logger = logging.getLogger(__name__)
settings = get_settings()


async def latest_overture_release() -> str | None:
    """Newest Overture release available on S3 (shared with the cold-load detector)."""
    from app.services.lead_generation_service import _latest_release_via_glob
    return await asyncio.to_thread(_latest_release_via_glob)


def _resolved_filter_from_category_key(category_key: str) -> dict:
    """Rebuild a category match filter from a stored category_key (codes joined by '|')."""
    codes = [c for c in (category_key or "").split("|") if c]
    return {
        "category_codes": codes,
        "category_patterns": [f"%{c}%" for c in codes],
        "keyword_patterns": [],
        "has_category": bool(codes),
    }


async def _refresh_one_area(session_factory, area: dict, release: str) -> int:
    """Re-pull one cached (area, category) from `release` and upsert it in place."""
    bbox = (area["xmin"], area["ymin"], area["xmax"], area["ymax"])
    center_lat = (area["ymin"] + area["ymax"]) / 2
    center_lng = (area["xmin"] + area["xmax"]) / 2
    resolved_filter = _resolved_filter_from_category_key(area["category_key"])

    rows = await _fetch_overture_area_rows(
        bbox, center_lat, center_lng,
        settings.OVERTURE_MIN_CONFIDENCE, resolved_filter,
        settings.OVERTURE_CACHE_PER_CATEGORY, release,
    )
    async with session_factory() as db:
        inserted = await _persist_overture_rows(db, rows)
        await db.execute(
            text(
                """
                UPDATE overture_loaded_areas
                SET loaded_at = NOW(), overture_release = :release, place_count = :pc
                WHERE id = :id
                """
            ),
            {"release": release, "pc": inserted, "id": area["id"]},
        )
        await db.commit()
    return inserted


async def refresh_overture_areas(session_factory, release: str | None = None) -> dict:
    """Refresh the taxonomy + every cached area from the latest Overture release."""
    if release is None:
        release = await latest_overture_release()
    if not release:
        logger.error("[OVERTURE_REFRESH] Could not determine latest release — aborting")
        return {"status": "no_release", "areas": 0}

    logger.info("[OVERTURE_REFRESH] Starting refresh to release=%s", release)

    # 1) Refresh the category taxonomy (categories can change between releases).
    async with session_factory() as db:
        try:
            await seed_overture_categories_from_csv(db, release)
        except Exception:
            logger.error("[OVERTURE_REFRESH] Category taxonomy re-seed failed", exc_info=True)

    # 2) Load the list of cached areas (with bbox bounds).
    async with session_factory() as db:
        areas = (
            await db.execute(
                text(
                    """
                    SELECT id, category_key,
                           ST_XMin(bbox) AS xmin, ST_YMin(bbox) AS ymin,
                           ST_XMax(bbox) AS xmax, ST_YMax(bbox) AS ymax
                    FROM overture_loaded_areas
                    ORDER BY loaded_at ASC
                    """
                )
            )
        ).mappings().all()

    # 3) Re-pull each area (sequential; per-area errors don't abort the run).
    refreshed = 0
    failed = 0
    for area in areas:
        try:
            n = await _refresh_one_area(session_factory, dict(area), release)
            refreshed += 1
            logger.info(
                "[OVERTURE_REFRESH] Area %s (%s) -> %s places",
                area["id"], area["category_key"], n,
            )
        except Exception:
            failed += 1
            logger.error("[OVERTURE_REFRESH] Area %s refresh failed", area["id"], exc_info=True)

    logger.info(
        "[OVERTURE_REFRESH] Done | release=%s areas=%s refreshed=%s failed=%s",
        release, len(areas), refreshed, failed,
    )
    return {"status": "ok", "release": release, "areas": len(areas), "refreshed": refreshed, "failed": failed}
