#!/usr/bin/env python3
"""Verify templates are correctly updated."""

import asyncio
from app.database.session import async_session_factory
import sqlalchemy as sa

async def verify():
    """Verify all three templates."""
    async with async_session_factory() as db:
        templates = ["Professional", "Value Proportion", "Network Outreach"]
        
        for template_name in templates:
            result = await db.execute(
                sa.text("""
                    SELECT name, subject, content 
                    FROM email_templates 
                    WHERE name = :name 
                    LIMIT 1
                """),
                {"name": template_name}
            )
            row = result.fetchone()
            
            if row:
                print(f"\n{'='*80}")
                print(f"TEMPLATE: {row.name}")
                print(f"{'='*80}")
                print(f"Subject: {row.subject}")
                print(f"\nContent:")
                print(row.content)
                print(f"\n{'='*80}\n")
            else:
                print(f"Template '{template_name}' not found!")

if __name__ == "__main__":
    asyncio.run(verify())

