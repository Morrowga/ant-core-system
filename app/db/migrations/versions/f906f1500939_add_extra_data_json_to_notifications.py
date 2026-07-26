"""add extra_data_json to notifications

Revision ID: f906f1500939
Revises: 7456c5c99e07
Create Date: 2026-07-20 16:24:44.023069
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'f906f1500939'
down_revision = '7456c5c99e07'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'notifications', 'extra_data_json'):
        op.add_column('notifications', sa.Column('extra_data_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'notifications', 'extra_data_json'):
        op.drop_column('notifications', 'extra_data_json')