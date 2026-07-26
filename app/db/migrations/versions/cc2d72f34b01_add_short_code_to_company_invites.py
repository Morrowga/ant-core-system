"""add short_code to company_invites

Revision ID: cc2d72f34b01
Revises: 779d775178a0
Create Date: 2026-07-23 15:40:40.383785
"""
import re
import secrets

from alembic import op
import sqlalchemy as sa


def _col_exists(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


revision = 'cc2d72f34b01'
down_revision = '779d775178a0'
branch_labels = None
depends_on = None

SHORT_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
SHORT_CODE_LENGTH = 6


def _slugify(name: str) -> str:
    match = re.search(r"[A-Za-z0-9]+", name or "")
    word = match.group(0) if match else "COMPANY"
    return word.upper()[:20]


def _generate_code(name: str) -> str:
    prefix = _slugify(name)
    suffix = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(SHORT_CODE_LENGTH))
    return f"{prefix}-{suffix}"


def upgrade() -> None:
    if not _col_exists(op.get_bind(), 'company_invites', 'short_code'):
        op.add_column('company_invites', sa.Column('short_code', sa.String(length=40), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT ci.id, c.name FROM company_invites ci "
        "JOIN companies c ON c.id = ci.company_id "
        "WHERE ci.short_code IS NULL"
    )).fetchall()

    used_codes: set[str] = set()
    for row in rows:
        code = _generate_code(row.name)
        while code in used_codes:
            code = _generate_code(row.name)
        used_codes.add(code)
        conn.execute(
            sa.text("UPDATE company_invites SET short_code = :code WHERE id = :id"),
            {"code": code, "id": row.id},
        )

    inspector = sa.inspect(conn)
    existing_constraints = {c["name"] for c in inspector.get_unique_constraints('company_invites')}
    op.alter_column('company_invites', 'short_code', nullable=False)
    if 'uq_company_invites_short_code' not in existing_constraints:
        op.create_unique_constraint('uq_company_invites_short_code', 'company_invites', ['short_code'])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_constraints = {c["name"] for c in inspector.get_unique_constraints('company_invites')}
    if 'uq_company_invites_short_code' in existing_constraints:
        op.drop_constraint('uq_company_invites_short_code', 'company_invites', type_='unique')
    if _col_exists(op.get_bind(), 'company_invites', 'short_code'):
        op.drop_column('company_invites', 'short_code')