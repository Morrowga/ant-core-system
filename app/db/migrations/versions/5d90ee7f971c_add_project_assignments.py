"""add project assignments

Revision ID: 5d90ee7f971c
Revises: 33c55cb2793e
Create Date: 2026-07-22 06:54:26.685109

Guarded -- project_assignments is part of current model metadata, so
0001 already creates it on a fresh DB.
"""
from alembic import op
import sqlalchemy as sa


revision = '5d90ee7f971c'
down_revision = '33c55cb2793e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'project_assignments' not in inspector.get_table_names():
        op.create_table('project_assignments',
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_project_assignments_project_id'), 'project_assignments', ['project_id'], unique=False)
        op.create_index(op.f('ix_project_assignments_user_id'), 'project_assignments', ['user_id'], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'project_assignments' in inspector.get_table_names():
        op.drop_index(op.f('ix_project_assignments_user_id'), table_name='project_assignments')
        op.drop_index(op.f('ix_project_assignments_project_id'), table_name='project_assignments')
        op.drop_table('project_assignments')
