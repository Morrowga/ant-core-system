"""add last_health_prompt_at to attendance sessions

Revision ID: bf93ffaa962f
Revises: 8a94c76f4389
Create Date: 2026-07-17 08:02:16.596990
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'bf93ffaa962f'
down_revision = '8a94c76f4389'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'attendance_sessions', 'last_health_prompt_at'):
        op.add_column('attendance_sessions', sa.Column('last_health_prompt_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'attendance_sessions', 'last_health_prompt_at'):
        op.drop_column('attendance_sessions', 'last_health_prompt_at')