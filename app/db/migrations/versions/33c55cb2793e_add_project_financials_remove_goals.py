"""add project financials, remove goals

Revision ID: 33c55cb2793e
Revises: 39fc1f101243
Create Date: 2026-07-22 06:42:25.458111

Guarded throughout. On a fresh database: 0001 already creates
project_expenses and the deal_price/estimated_*_date columns on projects
(current models), and never creates goals/goal_projects at all (Goals was
fully removed from the codebase) -- so every step here is checked first.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '33c55cb2793e'
down_revision = '39fc1f101243'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if 'project_expenses' not in existing_tables:
        op.create_table('project_expenses',
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('added_by', sa.BigInteger(), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['added_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_project_expenses_project_id'), 'project_expenses', ['project_id'], unique=False)

    if 'goal_projects' in existing_tables:
        op.drop_table('goal_projects')
    if 'goals' in existing_tables:
        op.drop_index('ix_goals_company_id', table_name='goals')
        op.drop_table('goals')

    project_columns = {c['name'] for c in inspector.get_columns('projects')}
    if 'deal_price' not in project_columns:
        op.add_column('projects', sa.Column('deal_price', sa.Float(), nullable=True))
    if 'estimated_start_date' not in project_columns:
        op.add_column('projects', sa.Column('estimated_start_date', sa.Date(), nullable=True))
    if 'estimated_end_date' not in project_columns:
        op.add_column('projects', sa.Column('estimated_end_date', sa.Date(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    project_columns = {c['name'] for c in inspector.get_columns('projects')} if 'projects' in existing_tables else set()

    if 'estimated_end_date' in project_columns:
        op.drop_column('projects', 'estimated_end_date')
    if 'estimated_start_date' in project_columns:
        op.drop_column('projects', 'estimated_start_date')
    if 'deal_price' in project_columns:
        op.drop_column('projects', 'deal_price')

    if 'goals' not in existing_tables:
        op.create_table('goals',
        sa.Column('title', sa.VARCHAR(length=255), autoincrement=False, nullable=False),
        sa.Column('description', sa.TEXT(), autoincrement=False, nullable=True),
        sa.Column('target_date', sa.DATE(), autoincrement=False, nullable=True),
        sa.Column('status', sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column('created_by', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('id', sa.BIGINT(), server_default=sa.text("nextval('goals_id_seq'::regclass)"), autoincrement=True, nullable=False),
        sa.Column('company_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('target_hours', sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], name='goals_company_id_fkey', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='goals_created_by_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='goals_pkey'),
        postgresql_ignore_search_path=False
        )
        op.create_index('ix_goals_company_id', 'goals', ['company_id'], unique=False)
    if 'goal_projects' not in existing_tables:
        op.create_table('goal_projects',
        sa.Column('goal_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.Column('project_id', sa.BIGINT(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['goal_id'], ['goals.id'], name='goal_projects_goal_id_fkey', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name='goal_projects_project_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('goal_id', 'project_id', name='goal_projects_pkey')
        )

    if 'project_expenses' in existing_tables:
        op.drop_index(op.f('ix_project_expenses_project_id'), table_name='project_expenses')
        op.drop_table('project_expenses')
