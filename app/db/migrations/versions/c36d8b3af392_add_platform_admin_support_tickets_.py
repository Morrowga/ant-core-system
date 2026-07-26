"""add platform admin, support tickets, company active flag

Revision ID: c36d8b3af392
Revises: f906f1500939
Create Date: 2026-07-20 18:32:22.669798

Guarded on the CREATE side (platform_admins, support_tickets,
companies.active are all part of current model metadata, so 0001 already
creates them on a fresh DB). The holidays/company_invites DROP statements
are left unconditional -- at this point in the chain those genuinely
exist (created by 0001 or the earlier bf24e509fd3d/e078f2cb1a3f steps)
regardless of whether the DB is fresh or old, so no guard is needed there.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c36d8b3af392'
down_revision = 'f906f1500939'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'platform_admins' not in existing_tables:
        op.create_table('platform_admins',
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_platform_admins_email'), 'platform_admins', ['email'], unique=True)

    if 'support_tickets' not in existing_tables:
        op.create_table('support_tickets',
        sa.Column('submitted_by_user_id', sa.BigInteger(), nullable=True),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('message', sa.String(length=4000), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_admin_id', sa.BigInteger(), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by_admin_id'], ['platform_admins.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['submitted_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_support_tickets_company_id'), 'support_tickets', ['company_id'], unique=False)

    if 'holidays' in existing_tables:
        op.drop_index('ix_holidays_company_id', table_name='holidays')
        op.drop_index('ix_holidays_country_code', table_name='holidays')
        op.drop_index('ix_holidays_date', table_name='holidays')
        op.drop_table('holidays')

    company_columns = {c['name'] for c in inspector.get_columns('companies')}
    if 'active' not in company_columns:
        op.add_column('companies', sa.Column('active', sa.Boolean(), nullable=False, server_default='true'))

    invite_columns = {c['name'] for c in inspector.get_columns('company_invites')}
    if 'timezone' in invite_columns:
        op.drop_column('company_invites', 'timezone')
    if 'holiday_country' in invite_columns:
        op.drop_column('company_invites', 'holiday_country')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    invite_columns = {c['name'] for c in inspector.get_columns('company_invites')}

    if 'holiday_country' not in invite_columns:
        op.add_column('company_invites', sa.Column('holiday_country', sa.VARCHAR(length=20), autoincrement=False, nullable=True))
    if 'timezone' not in invite_columns:
        op.add_column('company_invites', sa.Column('timezone', sa.VARCHAR(length=64), autoincrement=False, nullable=True))

    company_columns = {c['name'] for c in inspector.get_columns('companies')}
    if 'active' in company_columns:
        op.drop_column('companies', 'active')

    if 'holidays' not in inspector.get_table_names():
        op.create_table('holidays',
        sa.Column('country_code', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column('date', sa.DATE(), autoincrement=False, nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
        sa.Column('is_custom', sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column('id', sa.BIGINT(), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name='holidays_company_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='holidays_pkey')
        )
        op.create_index('ix_holidays_date', 'holidays', ['date'], unique=False)
        op.create_index('ix_holidays_country_code', 'holidays', ['country_code'], unique=False)
        op.create_index('ix_holidays_company_id', 'holidays', ['company_id'], unique=False)

    existing_tables = inspector.get_table_names()
    if 'support_tickets' in existing_tables:
        op.drop_index(op.f('ix_support_tickets_company_id'), table_name='support_tickets')
        op.drop_table('support_tickets')
    if 'platform_admins' in existing_tables:
        op.drop_index(op.f('ix_platform_admins_email'), table_name='platform_admins')
        op.drop_table('platform_admins')
