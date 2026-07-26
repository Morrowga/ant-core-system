"""add ended_at to work outside overrides

Revision ID: 41219eb83ca3
Revises: b20556281a11
Create Date: 2026-07-18 06:46:55.581729
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '41219eb83ca3'
down_revision = 'b20556281a11'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'work_outside_overrides', 'ended_at'):
        op.add_column('work_outside_overrides', sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    if not _col_exists(op.get_bind(), 'work_outside_overrides', 'created_at'):
        op.add_column('work_outside_overrides', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'work_outside_overrides', 'created_at'):
        op.drop_column('work_outside_overrides', 'created_at')
    if _col_exists(op.get_bind(), 'work_outside_overrides', 'ended_at'):
        op.drop_column('work_outside_overrides', 'ended_at')