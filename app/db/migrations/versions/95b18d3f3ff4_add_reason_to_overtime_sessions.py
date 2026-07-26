"""add reason to overtime sessions

Revision ID: 95b18d3f3ff4
Revises: d3e80a2087fc
Create Date: 2026-07-17 09:32:39.404912
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '95b18d3f3ff4'
down_revision = 'd3e80a2087fc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'overtime_sessions', 'reason'):
        op.add_column('overtime_sessions', sa.Column('reason', sa.Text(), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'overtime_sessions', 'reason'):
        op.drop_column('overtime_sessions', 'reason')