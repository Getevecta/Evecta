"""seed_default_email_templates

Revision ID: 7fcef134132d
Revises: 9240584ec370
Create Date: 2025-11-27 15:09:42.480275

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from uuid import uuid4
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision: str = '7fcef134132d'
down_revision: Union[str, Sequence[str], None] = '9240584ec370'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Default email templates to seed for each user
DEFAULT_TEMPLATES = [
    {
        "name": "Professional",
        "subject": "Exploring a Strategic Alignment with {{ business_name }}",
        "content": """Hello!

Greetings,

It's always inspiring to see how {{ business_name }} continues to shape the {{industry}} space. The clarity of your initiatives and the pace of execution reflect a team that knows exactly where the market is moving.

Based on what we've been building, we see a potential strategic alignment that could create value for both sides, not in a broad sense, but in particular areas where our strengths complement each other. We would like to briefly outline these intersections and explore whether collaboration could support your upcoming initiatives.

If you're open to it, a focused 15-minute conversation would be enough to determine whether it's worth moving forward. We are flexible and can adjust to a time that best suits your schedule.

With warm regards,

[Your Name]""",
        "category": "professional"
    },
   
    {
        "name": "Value Proportion",
        "subject": "Value Proportion",
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
        "subject": "Network Outreach",
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


def insert_templates_for_users(conn):
    """
    Insert or update default templates for all existing users.
    Updates existing templates with new content, or inserts if they don't exist.
    """
    # Get all user IDs
    users_result = conn.execute(sa.text("SELECT id FROM users"))
    users = users_result.fetchall()
    
    if not users:
        print("No users found. Skipping template seeding.")
        return
    
    now = datetime.now(timezone.utc)
    updated_count = 0
    inserted_count = 0
    
    for user_row in users:
        user_id = user_row[0]  # Keep as UUID object, not string
        
        for template in DEFAULT_TEMPLATES:
            # Check if template with this name already exists for this user
            # Cast user_id to UUID for proper comparison
            check_result = conn.execute(
                sa.text("""
                    SELECT id FROM email_templates 
                    WHERE user_id = CAST(:user_id AS uuid) AND name = :name
                """),
                {"user_id": str(user_id), "name": template["name"]}
            )
            
            existing_template = check_result.fetchone()
            
            if existing_template:
                # Template already exists, update it with new content
                conn.execute(
                    sa.text("""
                        UPDATE email_templates 
                        SET subject = :subject, 
                            content = :content, 
                            category = CAST(:category AS templatecategory),
                            updated_at = :updated_at
                        WHERE id = :template_id
                    """),
                    {
                        "template_id": str(existing_template[0]),
                        "subject": template["subject"],
                        "content": template["content"],
                        "category": template["category"],
                        "updated_at": now
                    }
                )
                updated_count += 1
            else:
                # Insert the template with proper enum casting
                conn.execute(
                    sa.text("""
                    INSERT INTO email_templates 
                    (id, user_id, name, subject, content, category, created_at, updated_at)
                    VALUES (CAST(:id AS uuid), CAST(:user_id AS uuid), :name, :subject, :content, CAST(:category AS templatecategory), :created_at, :updated_at)
                    """),
                    {
                    "id": str(uuid4()),
                    "user_id": str(user_id),
                    "name": template["name"],
                    "subject": template["subject"],
                    "content": template["content"],
                    "category": template["category"],
                    "created_at": now,
                    "updated_at": now
                    }
                    )
                inserted_count += 1
    
    print(f"Seeded default email templates for {len(users)} user(s): {inserted_count} inserted, {updated_count} updated")


def upgrade() -> None:
    """Upgrade schema - seed default email templates for all users."""
    conn = op.get_bind()
    insert_templates_for_users(conn)


def downgrade() -> None:
    """Downgrade schema - remove seeded default templates."""
    conn = op.get_bind()
    
    # Remove only the default templates we seeded (by name)
    default_names = [t["name"] for t in DEFAULT_TEMPLATES]
    
    for name in default_names:
        conn.execute(
            sa.text("DELETE FROM email_templates WHERE name = :name"),
            {"name": name}
        )
    
    print("Removed seeded default email templates")
