"""initial schema — full data model incl. pgvector report embeddings

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""
from alembic import op

from app.db.base import Base
import app.core.models  # noqa: F401  -- registers every core table on Base.metadata
import app.modules.hr.models  # noqa: F401  -- registers every HR-module table on Base.metadata

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension must exist before report_embeddings is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
