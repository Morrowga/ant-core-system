"""recover holidays table and company_invites columns (undo bad autogen)

Revision ID: d47e9c1b2a03
Revises: c36d8b3af392
Create Date: 2026-07-20 19:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'd47e9c1b2a03'
down_revision = 'c36d8b3af392'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Recreates the exact structure the previous migration incorrectly
    # dropped. The actual historical ROWS in holidays cannot be recovered
    # (no backup was available) -- this restores the table so it can be
    # re-seeded/re-populated going forward, it does not bring back deleted
    # data.
    op.create_table('holidays',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('country_code', sa.String(length=20), autoincrement=False, nullable=False),
        sa.Column('date', sa.Date(), autoincrement=False, nullable=False),
        sa.Column('name', sa.String(length=255), autoincrement=False, nullable=False),
        sa.Column('is_custom', sa.Boolean(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name='holidays_company_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='holidays_pkey'),
    )
    op.create_index('ix_holidays_company_id', 'holidays', ['company_id'], unique=False)
    op.create_index('ix_holidays_country_code', 'holidays', ['country_code'], unique=False)
    op.create_index('ix_holidays_date', 'holidays', ['date'], unique=False)

    op.add_column('company_invites', sa.Column('timezone', sa.String(length=64), nullable=True))
    op.add_column('company_invites', sa.Column('holiday_country', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('company_invites', 'holiday_country')
    op.drop_column('company_invites', 'timezone')
    op.drop_index('ix_holidays_date', table_name='holidays')
    op.drop_index('ix_holidays_country_code', table_name='holidays')
    op.drop_index('ix_holidays_company_id', table_name='holidays')
    op.drop_table('holidays')