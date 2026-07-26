"""add holiday_country to invites

Revision ID: 956972d95a6a
Revises: 89ec77eec782
Create Date: 2026-07-18 04:57:24.273880
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '956972d95a6a'
down_revision = '89ec77eec782'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'company_invites', 'holiday_country'):
        op.add_column('company_invites', sa.Column('holiday_country', sa.String(length=20), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'company_invites', 'holiday_country'):
        op.drop_column('company_invites', 'holiday_country')