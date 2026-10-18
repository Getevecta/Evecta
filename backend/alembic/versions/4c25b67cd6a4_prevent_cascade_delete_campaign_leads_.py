"""prevent_cascade_delete_campaign_leads_add_snapshot

Revision ID: 4c25b67cd6a4
Revises: 357f60418aa6
Create Date: 2026-02-03 15:22:26.491854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c25b67cd6a4'
down_revision: Union[str, Sequence[str], None] = '357f60418aa6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: Drop the existing foreign key constraint
    op.drop_constraint('campaign_leads_lead_id_fkey', 'campaign_leads', type_='foreignkey')
    
    # Step 2: Add snapshot columns to store lead data
    op.add_column('campaign_leads', sa.Column('business_name', sa.String(length=255), nullable=True))
    op.add_column('campaign_leads', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('campaign_leads', sa.Column('industry', sa.String(length=100), nullable=True))
    op.add_column('campaign_leads', sa.Column('address', sa.String(length=255), nullable=True))
    op.add_column('campaign_leads', sa.Column('contact_number', sa.String(length=50), nullable=True))
    op.add_column('campaign_leads', sa.Column('website', sa.String(length=255), nullable=True))
    op.add_column('campaign_leads', sa.Column('lead_score', sa.Integer(), nullable=True))
    
    # Step 3: Populate snapshot data from existing leads
    op.execute("""
        UPDATE campaign_leads cl
        SET 
            business_name = l.business_name,
            email = l.email,
            industry = l.industry,
            address = l.address,
            contact_number = l.contact_number,
            website = l.website,
            lead_score = l.lead_score
        FROM leads l
        WHERE cl.lead_id = l.id
    """)
    
    # Step 4: Make lead_id nullable
    op.alter_column('campaign_leads', 'lead_id', nullable=True)
    
    # Step 5: Recreate the foreign key constraint with SET NULL
    op.create_foreign_key(
        'campaign_leads_lead_id_fkey',
        'campaign_leads', 'leads',
        ['lead_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Step 1: Drop the foreign key constraint
    op.drop_constraint('campaign_leads_lead_id_fkey', 'campaign_leads', type_='foreignkey')
    
    # Step 2: Make lead_id non-nullable (this will fail if there are NULL values)
    op.alter_column('campaign_leads', 'lead_id', nullable=False)
    
    # Step 3: Remove snapshot columns
    op.drop_column('campaign_leads', 'lead_score')
    op.drop_column('campaign_leads', 'website')
    op.drop_column('campaign_leads', 'contact_number')
    op.drop_column('campaign_leads', 'address')
    op.drop_column('campaign_leads', 'industry')
    op.drop_column('campaign_leads', 'email')
    op.drop_column('campaign_leads', 'business_name')
    
    # Step 4: Recreate the original foreign key constraint with CASCADE
    op.create_foreign_key(
        'campaign_leads_lead_id_fkey',
        'campaign_leads', 'leads',
        ['lead_id'], ['id'],
        ondelete='CASCADE'
    )
