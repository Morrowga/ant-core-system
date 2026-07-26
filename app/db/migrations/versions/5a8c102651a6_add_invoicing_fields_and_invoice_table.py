"""add invoicing fields and invoice table

Revision ID: 5a8c102651a6
Revises: cb033f8c8d0b
Create Date: 2026-07-21 20:15:17.554318

Guarded throughout -- invoices table and the three users columns are all
part of current model metadata, so 0001 already creates them on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = '5a8c102651a6'
down_revision = 'cb033f8c8d0b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'invoices' not in inspector.get_table_names():
        op.create_table('invoices',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('period_start', sa.Date(), nullable=False),
        sa.Column('period_end', sa.Date(), nullable=False),
        sa.Column('hourly_fee', sa.Float(), nullable=False),
        sa.Column('total_hours', sa.Float(), nullable=False),
        sa.Column('total_amount', sa.Float(), nullable=False),
        sa.Column('actual_working_hours', sa.Boolean(), nullable=False),
        sa.Column('pdf_url', sa.String(length=1024), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_invoices_company_id'), 'invoices', ['company_id'], unique=False)
        op.create_index(op.f('ix_invoices_user_id'), 'invoices', ['user_id'], unique=False)

    user_columns = {c['name'] for c in inspector.get_columns('users')}
    if 'job_type' not in user_columns:
        op.add_column('users', sa.Column('job_type', sa.String(length=20), nullable=False, server_default='full_time'))
    if 'actual_working_hours' not in user_columns:
        op.add_column('users', sa.Column('actual_working_hours', sa.Boolean(), nullable=False, server_default='true'))
    if 'hourly_fee' not in user_columns:
        op.add_column('users', sa.Column('hourly_fee', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    user_columns = {c['name'] for c in inspector.get_columns('users')}

    if 'hourly_fee' in user_columns:
        op.drop_column('users', 'hourly_fee')
    if 'actual_working_hours' in user_columns:
        op.drop_column('users', 'actual_working_hours')
    if 'job_type' in user_columns:
        op.drop_column('users', 'job_type')

    if 'invoices' in inspector.get_table_names():
        op.drop_index(op.f('ix_invoices_user_id'), table_name='invoices')
        op.drop_index(op.f('ix_invoices_company_id'), table_name='invoices')
        op.drop_table('invoices')
