"""add reason, outside-desk detection, leave time fields

Revision ID: d3e80a2087fc
Revises: bf93ffaa962f
Create Date: 2026-07-17 09:03:14.367685
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'd3e80a2087fc'
down_revision = 'bf93ffaa962f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'attendance_sessions', 'checked_in_outside_desk'):
        op.add_column('attendance_sessions', sa.Column('checked_in_outside_desk', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    if not _col_exists(op.get_bind(), 'leave_requests', 'start_time'):
        op.add_column('leave_requests', sa.Column('start_time', sa.String(length=5), nullable=True))
    if not _col_exists(op.get_bind(), 'leave_requests', 'end_time'):
        op.add_column('leave_requests', sa.Column('end_time', sa.String(length=5), nullable=True))
    if not _col_exists(op.get_bind(), 'work_outside_overrides', 'reason'):
        op.add_column('work_outside_overrides', sa.Column('reason', sa.Text(), nullable=True))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'work_outside_overrides', 'reason'):
        op.drop_column('work_outside_overrides', 'reason')
    if _col_exists(op.get_bind(), 'leave_requests', 'end_time'):
        op.drop_column('leave_requests', 'end_time')
    if _col_exists(op.get_bind(), 'leave_requests', 'start_time'):
        op.drop_column('leave_requests', 'start_time')
    if _col_exists(op.get_bind(), 'attendance_sessions', 'checked_in_outside_desk'):
        op.drop_column('attendance_sessions', 'checked_in_outside_desk')