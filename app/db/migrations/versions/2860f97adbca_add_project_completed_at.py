"""add project completed_at

Revision ID: 2860f97adbca
Revises: 5d90ee7f971c
Create Date: 2026-07-22 08:13:27.772829
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '2860f97adbca'
down_revision = '5d90ee7f971c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'projects', 'completed_at'):
        op.add_column('projects', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'projects', 'completed_at'):
        op.drop_column('projects', 'completed_at')