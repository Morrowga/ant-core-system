"""add health checkin prompts and last_health_prompt_at

Revision ID: 8a94c76f4389
Revises: 0002
Create Date: 2026-07-17 07:30:32.795135

Guarded with a table-existence check. On a fresh database, 0001 already
creates health_checkin_prompts (it builds from CURRENT model metadata,
and HealthCheckinPrompt is a current model) -- this migration only does
real work on an older database that predates that model being added to 0001.
"""
from alembic import op
import sqlalchemy as sa


revision = '8a94c76f4389'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'health_checkin_prompts' not in inspector.get_table_names():
        op.create_table('health_checkin_prompts',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=30), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_health_checkin_prompts_company_id'), 'health_checkin_prompts', ['company_id'], unique=False)
        op.create_index(op.f('ix_health_checkin_prompts_user_id'), 'health_checkin_prompts', ['user_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'health_checkin_prompts' in inspector.get_table_names():
        op.drop_index(op.f('ix_health_checkin_prompts_user_id'), table_name='health_checkin_prompts')
        op.drop_index(op.f('ix_health_checkin_prompts_company_id'), table_name='health_checkin_prompts')
        op.drop_table('health_checkin_prompts')
