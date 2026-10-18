#!/usr/bin/env python3
"""Manually update email templates with new content."""

import asyncio
from app.database.session import async_session_factory
from app.core.config import get_settings
import sqlalchemy as sa
from datetime import datetime, timezone

# Updated email templates content
UPDATED_TEMPLATES = [
    {
        "name": "Professional",
        "subject": "Exploring a Strategic Alignment with {{business_name}}",
        "content": """Hello!

Greetings,

It's always inspiring to see how {{business_name}} continues to shape the {{industry}} space. The clarity of your initiatives and the pace of execution reflect a team that knows exactly where the market is moving.

Based on what we've been building, we see a potential strategic alignment that could create value for both sides, not in a broad sense, but in particular areas where our strengths complement each other. We would like to briefly outline these intersections and explore whether collaboration could support your upcoming initiatives.

If you're open to it, a focused 15-minute conversation would be enough to determine whether it's worth moving forward. We are flexible and can adjust to a time that best suits your schedule.

With warm regards,

[Your Name]""",
        "category": "professional"
    },
   
    {
        "name": "Value Proportion",
        "subject": "Value proposition for {{business_name}}",
        "content": """Hello Team,

While exploring standout organizations in the {{industry}} space, {{business_name}} consistently stood out. The pace and quality of your recent growth truly reflect strong leadership and a clear operational vision.

Given your role, I thought you might be interested in some of the operational gains companies in your segment have been achieving through targeted optimization. For example, similar organizations recently saw:

 • 30% reduction in operational costs

 • 50% faster processing across key workflows

 • 95% accuracy improvements in routine tasks

What's notable is that these improvements were achieved without major restructuring—just smarter systems and refined processes.

If it's helpful, I'd be glad to walk you through the approach in a quick 10-minute conversation and share how these results could translate to {{business_name}}.

Best regards,

[Your Name]""",
        "category": "value-proposition"
    },
   
    {
        "name": "Network Outreach",
        "subject": "Connecting with fellow {{industry}} professionals",
        "content": """Hi {{business_name}} Team,

Looking at how different teams are adapting to shifts in the {{industry}} landscape, {{business_name}} caught my attention for the strength and precision of your recent initiatives.

I'd like to connect and exchange insights, as we collaborate with organizations facing similar challenges in this sector. A brief introductory conversation could help us explore whether there's any meaningful alignment.

If you're open to it, I'd appreciate the chance to connect briefly and exchange insights. A quick coffee chat or short virtual meeting works perfectly.

Looking forward to connecting,

Best regards,

[Your Name]""",
        "category": "network-outreach"
    }
]


async def update_templates():
    """Update email templates in the database."""
    now = datetime.now(timezone.utc)
    updated_count = 0
    
    async with async_session_factory() as db:
        for template in UPDATED_TEMPLATES:
            # Update all templates with matching name
            result = await db.execute(
                sa.text("""
                    UPDATE email_templates 
                    SET subject = :subject,
                        content = :content,
                        category = CAST(:category AS templatecategory),
                        updated_at = :updated_at
                    WHERE name = :name
                """),
                {
                    "name": template["name"],
                    "subject": template["subject"],
                    "content": template["content"],
                    "category": template["category"],
                    "updated_at": now
                }
            )
            updated_count += result.rowcount
            print(f"Updated {result.rowcount} template(s) with name '{template['name']}'")
        
        await db.commit()
    
    print(f"\nSuccessfully updated {updated_count} email template(s) with new content!")
    print("Please restart your backend server and refresh the frontend to see the changes.")


if __name__ == "__main__":
    asyncio.run(update_templates())

