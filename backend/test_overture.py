"""
Standalone smoke test for get_leads_overture (direct DuckDB → Overture S3 path).

Run from the backend folder:

    cd d:\\sadhan2025\\Evecta\\backend
    python test_overture.py
    python test_overture.py "restaurant" "Gordon, Sydney" 10
    python test_overture.py "childcare" "Kathmandu, Nepal" 8

Args (all optional):
    1) industry        default: "childcare"
    2) location        default: "Gordon, Sydney"
    3) radius_km       default: 10
    4) limit           default: 20

What it checks:
    - DuckDB can read Overture's public S3 parquet (anonymous access).
    - The configured OVERTURE_RELEASE actually exists.
    - Geocoding (reuses geocode_location) resolves the location.
    - get_leads_overture returns lead dicts within the requested radius.
    - How many SECONDS a cold per-search S3 pull takes (the key number that
      tells us how urgently the PostGIS cache is needed).

Requirements:
    pip install duckdb        # the only missing lib
    A valid APP_GOOGLE_MAPS_API_KEY in backend/.env (geocoding still uses Google).
    Internet access (DuckDB pulls httpfs/spatial extensions + reads S3).
"""

import asyncio
import sys
import time

from app.core.config import get_settings
from app.services.lead_generation_service import get_leads_overture, resolve_overture_filter


async def main() -> None:
    industry = sys.argv[1] if len(sys.argv) > 1 else "childcare"
    location = sys.argv[2] if len(sys.argv) > 2 else "Gordon, Sydney"
    radius_km = float(sys.argv[3]) if len(sys.argv) > 3 else 10.0
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 20

    settings = get_settings()

    print("=" * 70)
    print("Overture standalone test")
    print("=" * 70)
    print(f"industry      : {industry!r}")
    print(f"location      : {location!r}")
    print(f"radius_km     : {radius_km}")
    print(f"limit         : {limit}")
    print(f"OVERTURE_RELEASE      : {settings.OVERTURE_RELEASE}")
    print(f"OVERTURE_S3_BASE      : {settings.OVERTURE_S3_BASE}")
    print(f"OVERTURE_MIN_CONFIDENCE: {settings.OVERTURE_MIN_CONFIDENCE}")
    print(f"OVERTURE_AREA_BUFFER_KM: {settings.OVERTURE_AREA_BUFFER_KM}")
    print("-" * 70)

    # Show how the industry resolves to Overture categories (mapping sanity check)
    resolved = resolve_overture_filter(industry, None)
    print("resolved filter:")
    print(f"  category_patterns: {resolved['category_patterns']}")
    print(f"  keyword_patterns : {resolved['keyword_patterns']}")
    print(f"  has_category     : {resolved['has_category']}")
    print(f"  strict_intent    : {resolved['strict_intent']}")
    print("-" * 70)

    from app.database.session import async_session_factory

    async def run_once(db, label):
        start = time.perf_counter()
        try:
            leads, error_info = await get_leads_overture(
                industry=industry,
                location=location,
                search_radius_km=radius_km,
                limit=limit,
                search_terms=None,
                db=db,  # cached path: cold-load once, then PostGIS
            )
        except Exception as exc:  # noqa: BLE001 — smoke test: surface the raw error
            elapsed = time.perf_counter() - start
            print(f"\n!! {label} FAILED after {elapsed:.1f}s")
            print(f"!! {type(exc).__name__}: {exc}")
            print("\nCommon causes:")
            print("  - S3 credentials error  -> DuckDB needs anonymous S3 access for the public bucket")
            print("  - 'No files found'      -> OVERTURE_RELEASE is wrong / does not exist")
            print("  - geocoding_failed      -> check APP_GOOGLE_MAPS_API_KEY in backend/.env")
            raise
        elapsed = time.perf_counter() - start
        return leads, error_info, elapsed

    print("Run 1 (COLD — pulls the area from S3 and caches it into overture_places)...")
    async with async_session_factory() as db:
        leads, error_info, cold = await run_once(db, "COLD")
    print(f"  cold: {len(leads)} leads in {cold:.1f}s | error_info={error_info}")

    print("Run 2 (WARM — should hit PostGIS only, no S3)...")
    async with async_session_factory() as db:
        leads, error_info, warm = await run_once(db, "WARM")
    print(f"  warm: {len(leads)} leads in {warm:.1f}s")

    print("-" * 70)
    for i, lead in enumerate(leads, 1):
        print(f"{i:>2}. {lead.get('business_name')}")
        print(f"     industry : {lead.get('industry')}")
        print(f"     address  : {lead.get('address')}")
        print(f"     website  : {lead.get('website')}")
        print(f"     phone    : {lead.get('contact_number')}")

    print("=" * 70)
    print(f"SUMMARY ({industry} within {radius_km}km of {location}):")
    print(f"  COLD load: {cold:.1f}s   WARM query: {warm:.1f}s   "
          f"speedup: {cold / warm:.0f}x" if warm > 0 else "")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
