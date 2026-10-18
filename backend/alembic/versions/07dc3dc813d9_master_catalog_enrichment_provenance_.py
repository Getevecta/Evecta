"""master catalog: enrichment + provenance columns + lead_log_leads.overture_id

Revision ID: 07dc3dc813d9
Revises: 93ea89485be5
Create Date: 2026-07-17 10:28:38.417252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '07dc3dc813d9'
down_revision: Union[str, Sequence[str], None] = '93ea89485be5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # HAND-EDITED after autogenerate: removed unrelated ops that autogenerate
    # picked up as drift — (1) DROPs of the LangGraph checkpointer tables
    # (checkpoints/checkpoint_blobs/checkpoint_writes/checkpoint_migrations),
    # which live outside SQLAlchemy metadata and must NOT be dropped, and
    # (2) an unrelated ix_roles_name unique flip. This migration is ONLY the
    # master-catalog columns (docs/OVERTURE_EMAIL_POISONING_AND_MASTER_CATALOG.md §6.1).
    op.add_column('lead_log_leads', sa.Column('overture_id', sa.String(length=64), nullable=True))
    op.create_index(op.f('ix_lead_log_leads_overture_id'), 'lead_log_leads', ['overture_id'], unique=False)
    op.add_column('overture_places', sa.Column('scraped_email', sa.String(length=320), nullable=True))
    op.add_column('overture_places', sa.Column('email_source', sa.String(length=20), nullable=True))
    op.add_column('overture_places', sa.Column('lead_score', sa.Integer(), nullable=True))
    op.add_column('overture_places', sa.Column('enrichment_status', sa.String(length=20), nullable=True))
    op.add_column('overture_places', sa.Column('enriched_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('overture_places', sa.Column('hunter_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('overture_places', sa.Column('services', sa.Text(), nullable=True))
    op.add_column('overture_places', sa.Column('website_summary', sa.Text(), nullable=True))
    op.add_column('overture_places', sa.Column('business_description', sa.Text(), nullable=True))
    op.create_index(op.f('ix_overture_places_enrichment_status'), 'overture_places', ['enrichment_status'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # HAND-EDITED: checkpointer re-creates and the roles index flip removed
    # (see note in upgrade()).
    op.drop_index(op.f('ix_overture_places_enrichment_status'), table_name='overture_places')
    op.drop_column('overture_places', 'business_description')
    op.drop_column('overture_places', 'website_summary')
    op.drop_column('overture_places', 'services')
    op.drop_column('overture_places', 'hunter_data')
    op.drop_column('overture_places', 'enriched_at')
    op.drop_column('overture_places', 'enrichment_status')
    op.drop_column('overture_places', 'lead_score')
    op.drop_column('overture_places', 'email_source')
    op.drop_column('overture_places', 'scraped_email')
    op.drop_index(op.f('ix_lead_log_leads_overture_id'), table_name='lead_log_leads')
    op.drop_column('lead_log_leads', 'overture_id')
    # ### end Alembic commands ###
