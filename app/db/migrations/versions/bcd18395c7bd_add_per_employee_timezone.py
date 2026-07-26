"""add per-employee timezone

Revision ID: bcd18395c7bd
Revises: 95b18d3f3ff4
Create Date: 2026-07-17 09:54:05.436254
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'bcd18395c7bd'
down_revision = '95b18d3f3ff4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'companies', 'working_hours_mode'):
        op.add_column('companies', sa.Column('working_hours_mode', sa.String(length=20), nullable=False, server_default=sa.text("'company_timezone'")))
    if not _col_exists(op.get_bind(), 'users', 'timezone'):
        op.add_column('users', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'users', 'timezone'):
        op.drop_column('users', 'timezone')
    if _col_exists(op.get_bind(), 'companies', 'working_hours_mode'):
        op.drop_column('companies', 'working_hours_mode')