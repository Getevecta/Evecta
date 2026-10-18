#!/usr/bin/env python3
"""Check what templates are actually in the database."""

import asyncio
from app.database.session import async_session_factory
import sqlalchemy as sa

async def check_templates():
    """Check templates in database."""
    async with async_session_factory() as db:
        # Get all templates
        result = await db.execute(
            sa.text("""
                SELECT id, user_id, name, subject, LEFT(content, 100) as content_preview, updated_at
                FROM email_templates
                WHERE name IN ('Professional', 'Network Outreach', 'Value Proportion')
                ORDER BY name, updated_at DESC
            """)
        )
        
        templates = result.fetchall()
        
        print(f"\nFound {len(templates)} template(s) with default names:\n")
        for template in templates:
            print(f"Name: {template.name}")
            print(f"Subject: {template.subject}")
            print(f"Content preview: {template.content_preview}...")
            print(f"Updated at: {template.updated_at}")
            print(f"User ID: {template.user_id}")
            print("-" * 80)


if __name__ == "__main__":
    asyncio.run(check_templates())

