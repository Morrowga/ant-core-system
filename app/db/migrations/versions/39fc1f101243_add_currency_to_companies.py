"""add currency to companies

Revision ID: 39fc1f101243
Revises: 8097aa6c1a92
Create Date: 2026-07-22 04:40:07.665023
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '39fc1f101243'
down_revision = '8097aa6c1a92'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'companies', 'currency'):
        op.add_column('companies', sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'companies', 'currency'):
        op.drop_column('companies', 'currency')