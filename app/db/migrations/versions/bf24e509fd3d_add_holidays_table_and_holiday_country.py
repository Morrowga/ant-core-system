"""add holidays table and holiday_country

Revision ID: bf24e509fd3d
Revises: e078f2cb1a3f
Create Date: 2026-07-17 11:42:38.349101

Guarded -- holidays table and users.holiday_country are both part of
current model metadata, so 0001 already creates them on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = 'bf24e509fd3d'
down_revision = 'e078f2cb1a3f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'holidays' not in inspector.get_table_names():
        op.create_table('holidays',
        sa.Column('country_code', sa.String(length=20), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_custom', sa.Boolean(), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_holidays_company_id'), 'holidays', ['company_id'], unique=False)
        op.create_index(op.f('ix_holidays_country_code'), 'holidays', ['country_code'], unique=False)
        op.create_index(op.f('ix_holidays_date'), 'holidays', ['date'], unique=False)

    user_columns = {c['name'] for c in inspector.get_columns('users')}
    if 'holiday_country' not in user_columns:
        op.add_column('users', sa.Column('holiday_country', sa.String(length=20), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c['name'] for c in inspector.get_columns('users')}

    if 'holiday_country' in user_columns:
        op.drop_column('users', 'holiday_country')
    if 'holidays' in inspector.get_table_names():
        op.drop_index(op.f('ix_holidays_date'), table_name='holidays')
        op.drop_index(op.f('ix_holidays_country_code'), table_name='holidays')
        op.drop_index(op.f('ix_holidays_company_id'), table_name='holidays')
        op.drop_table('holidays')
