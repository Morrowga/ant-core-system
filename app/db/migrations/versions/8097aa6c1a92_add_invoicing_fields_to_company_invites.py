"""add invoicing fields to company_invites

Revision ID: 8097aa6c1a92
Revises: 5a8c102651a6
Create Date: 2026-07-21 21:04:04.396405
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '8097aa6c1a92'
down_revision = '5a8c102651a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'company_invites', 'job_type'):
        op.add_column('company_invites', sa.Column('job_type', sa.String(length=20), nullable=False, server_default='full_time'))
    if not _col_exists(op.get_bind(), 'company_invites', 'actual_working_hours'):
        op.add_column('company_invites', sa.Column('actual_working_hours', sa.Boolean(), nullable=False, server_default='true'))
    if not _col_exists(op.get_bind(), 'company_invites', 'hourly_fee'):
        op.add_column('company_invites', sa.Column('hourly_fee', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'company_invites', 'hourly_fee'):
        op.drop_column('company_invites', 'hourly_fee')
    if _col_exists(op.get_bind(), 'company_invites', 'actual_working_hours'):
        op.drop_column('company_invites', 'actual_working_hours')
    if _col_exists(op.get_bind(), 'company_invites', 'job_type'):
        op.drop_column('company_invites', 'job_type')