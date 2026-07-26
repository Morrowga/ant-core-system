"""add language to users and company_invites

Revision ID: 779d775178a0
Revises: 9824839e2f2b
Create Date: 2026-07-23 12:49:15.892957
"""
from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = '779d775178a0'
down_revision = '9824839e2f2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'users', 'language'):
        op.add_column('users', sa.Column('language', sa.String(length=10), nullable=False, server_default='en'))
    if not _col_exists(op.get_bind(), 'company_invites', 'language'):
        op.add_column('company_invites', sa.Column('language', sa.String(length=10), nullable=False, server_default='en'))


def downgrade() -> None:
    if _col_exists(op.get_bind(), 'users', 'language'):
        op.drop_column('users', 'language')
    if _col_exists(op.get_bind(), 'company_invites', 'language'):
        op.drop_column('company_invites', 'language')