"""add late/early tracking and break sessions

Revision ID: fecd79cc1d4e
Revises: 956972d95a6a
Create Date: 2026-07-18 06:02:15.107948

Guarded -- break_sessions and the two attendance_sessions columns are all
part of current model metadata, so 0001 already creates them on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = 'fecd79cc1d4e'
down_revision = '956972d95a6a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if 'break_sessions' not in inspector.get_table_names():
        op.create_table('break_sessions',
        sa.Column('attendance_session_id', sa.BigInteger(), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(['attendance_session_id'], ['attendance_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_break_sessions_attendance_session_id'), 'break_sessions', ['attendance_session_id'], unique=False)

    session_columns = {c['name'] for c in inspector.get_columns('attendance_sessions')}
    if 'late_minutes' not in session_columns:
        op.add_column('attendance_sessions', sa.Column('late_minutes', sa.Integer(), nullable=True))
    if 'early_checkout_minutes' not in session_columns:
        op.add_column('attendance_sessions', sa.Column('early_checkout_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    session_columns = {c['name'] for c in inspector.get_columns('attendance_sessions')}

    if 'early_checkout_minutes' in session_columns:
        op.drop_column('attendance_sessions', 'early_checkout_minutes')
    if 'late_minutes' in session_columns:
        op.drop_column('attendance_sessions', 'late_minutes')

    if 'break_sessions' in inspector.get_table_names():
        op.drop_index(op.f('ix_break_sessions_attendance_session_id'), table_name='break_sessions')
        op.drop_table('break_sessions')
