"""add desk location requests

Revision ID: 7456c5c99e07
Revises: a73ebcad84a4
Create Date: 2026-07-20 14:57:01.622941

Guarded -- desk_location_requests is part of current model metadata, so
0001 already creates it on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = '7456c5c99e07'
down_revision = 'a73ebcad84a4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'desk_location_requests' not in inspector.get_table_names():
        op.create_table('desk_location_requests',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('decided_by', sa.BigInteger(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_desk_location_requests_company_id'), 'desk_location_requests', ['company_id'], unique=False)
        op.create_index(op.f('ix_desk_location_requests_user_id'), 'desk_location_requests', ['user_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'desk_location_requests' in inspector.get_table_names():
        op.drop_index(op.f('ix_desk_location_requests_user_id'), table_name='desk_location_requests')
        op.drop_index(op.f('ix_desk_location_requests_company_id'), table_name='desk_location_requests')
        op.drop_table('desk_location_requests')
