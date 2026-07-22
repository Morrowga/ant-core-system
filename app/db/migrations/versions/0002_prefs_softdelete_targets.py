"""notification preferences table, knowledge soft delete, goal target hours

Guarded with IF NOT EXISTS / checkfirst so this is a no-op on fresh databases
where 0001 already created everything from current metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14
"""
from alembic import op

from app.db.base import Base
import app.models  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["notification_preferences"].create(bind, checkfirst=True)
    op.execute("ALTER TABLE knowledge_posts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("ALTER TABLE goals ADD COLUMN IF NOT EXISTS target_hours DOUBLE PRECISION")


def downgrade() -> None:
    op.execute("ALTER TABLE goals DROP COLUMN IF EXISTS target_hours")
    op.execute("ALTER TABLE knowledge_posts DROP COLUMN IF EXISTS deleted_at")
    op.execute("DROP TABLE IF EXISTS notification_preferences")
