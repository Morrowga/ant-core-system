"""add ai insights tables

Revision ID: 9824839e2f2b
Revises: 2860f97adbca
Create Date: 2026-07-22 09:11:30.606313

Guarded -- both tables are part of current model metadata, so 0001
already creates them on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = '9824839e2f2b'
down_revision = '2860f97adbca'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'company_overview_analyses' not in existing_tables:
        op.create_table('company_overview_analyses',
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('narrative_text', sa.Text(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_company_overview_analyses_company_id'), 'company_overview_analyses', ['company_id'], unique=False)

    if 'project_analyses' not in existing_tables:
        op.create_table('project_analyses',
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('metrics_json', sa.JSON(), nullable=False),
        sa.Column('narrative_text', sa.Text(), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_project_analyses_company_id'), 'project_analyses', ['company_id'], unique=False)
        op.create_index(op.f('ix_project_analyses_project_id'), 'project_analyses', ['project_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'project_analyses' in existing_tables:
        op.drop_index(op.f('ix_project_analyses_project_id'), table_name='project_analyses')
        op.drop_index(op.f('ix_project_analyses_company_id'), table_name='project_analyses')
        op.drop_table('project_analyses')
    if 'company_overview_analyses' in existing_tables:
        op.drop_index(op.f('ix_company_overview_analyses_company_id'), table_name='company_overview_analyses')
        op.drop_table('company_overview_analyses')
