"""add timezone to company invites

Revision ID: e078f2cb1a3f
Revises: 3a484c037317
Create Date: 2026-07-17 11:21:28.317102
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'e078f2cb1a3f'
down_revision = '3a484c037317'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'company_invites', 'timezone'):
        op.add_column('company_invites', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'company_invites', 'timezone'):
        op.drop_column('company_invites', 'timezone')