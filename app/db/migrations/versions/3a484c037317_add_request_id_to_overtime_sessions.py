"""add request_id to overtime sessions

Revision ID: 3a484c037317
Revises: 5e05097c6f73
Create Date: 2026-07-17 10:48:59.179623
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _fk_exists(bind, table_name, referred_table):
    inspector = sa.inspect(bind)
    return any(fk["referred_table"] == referred_table for fk in inspector.get_foreign_keys(table_name))


revision = '3a484c037317'
down_revision = '5e05097c6f73'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'overtime_sessions', 'request_id'):
        op.add_column('overtime_sessions', sa.Column('request_id', sa.BigInteger(), nullable=True))
    if not _fk_exists(op.get_bind(), 'overtime_sessions', 'overtime_requests'):
        op.create_foreign_key(None, 'overtime_sessions', 'overtime_requests', ['request_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    if _fk_exists(op.get_bind(), 'overtime_sessions', 'overtime_requests'):
        op.drop_constraint(None, 'overtime_sessions', type_='foreignkey')
    if _col_exists(op.get_bind(), 'overtime_sessions', 'request_id'):
        op.drop_column('overtime_sessions', 'request_id')