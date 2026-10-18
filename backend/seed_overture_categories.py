"""
Seed the Overture category tables.

Run from the backend folder:
    cd d:\\sadhan2025\\Evecta\\backend
    python seed_overture_categories.py

- Loads the official Overture category taxonomy into overture_categories.
- Migrates the in-code OVERTURE_CATEGORY_MAP into overture_category_aliases seed rows.

Idempotent (upserts) — safe to re-run. The monthly refresh job reuses
seed_overture_categories_from_csv().
"""

import asyncio

from app.database.session import async_session_factory
from app.services.overture_category_service import (
    seed_aliases_from_static_map,
    seed_overture_categories_from_csv,
)


async def main() -> None:
    async with async_session_factory() as db:
        print("Seeding overture_categories from CSV ...")
        n_cat = await seed_overture_categories_from_csv(db)
        print(f"  categories: {n_cat}")

        print("Seeding overture_category_aliases from static map ...")
        n_alias = await seed_aliases_from_static_map(db)
        print(f"  aliases: {n_alias}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
