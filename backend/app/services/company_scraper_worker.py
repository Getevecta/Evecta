import asyncio
import json
from uuid import UUID

from fastapi import HTTPException
from app.models.company import Company
from app.database.session import async_session_factory
from app.services.company_scraper_service import (
    run_company_scraper_sync,
    scrape_website_text
)
from app.services.company_service import update_company
from app.schemas.company import CompanyUpdate


async def process_company_website_async(company_id: UUID, website_url: str):
    """
    Async background scraper.
    Works inside FastAPI's event loop.
    """

    try:
        async with async_session_factory() as session:

            # Fetch company
            company = await session.get(Company, str(company_id))
            if not company:
                raise HTTPException(
                    status_code=404,
                    detail=f"Company not found: {company_id}"
                )

            owner_id = company.user_id

            # Scrape text — sync I/O, run in threadpool to avoid blocking event loop
            text = await asyncio.to_thread(scrape_website_text, website_url)
            if not text or len(text) < 50:
                raise HTTPException(
                    status_code=422,
                    detail="Website scraping failed or returned insufficient content."
                )

            # LLM extraction — CPU/network-heavy sync call, run in threadpool
            raw_data = await asyncio.to_thread(
                run_company_scraper_sync, website_url, text, owner_id
            )
            if not raw_data:
                raise HTTPException(
                    status_code=500,
                    detail="Structured data extraction failed from LLM."
                )

            # Validate payload
            try:
                update_payload = CompanyUpdate(**raw_data)
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail="Failed to process scraped data."
                )

            # Update DB
            try:
                await update_company(
                    db=session,
                    company_id=str(company_id),
                    user_id=owner_id,
                    payload=update_payload,
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save changes. Please try again."
                )

    except HTTPException:
        # Re-raise API-safe error
        raise

    except Exception as e:
        # Global fallback
        raise HTTPException(
            status_code=500,
            detail="Background processing failed."
        )
