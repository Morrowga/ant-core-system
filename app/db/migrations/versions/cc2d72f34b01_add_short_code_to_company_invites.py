"""add short_code to company_invites

Revision ID: cc2d72f34b01
Revises: 779d775178a0
Create Date: 2026-07-23 15:40:40.383785
"""
import re
import secrets

from alembic import op
import sqlalchemy as sa


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
    # Step 1: add the column as NULLABLE first -- existing rows can't
    # satisfy a NOT NULL constraint with no default, since each row needs
    # a DIFFERENT generated code, not one shared value.
    op.add_column('company_invites', sa.Column('short_code', sa.String(length=40), nullable=True))

    # Step 2: backfill every existing row with a unique generated code.
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT ci.id, c.name FROM company_invites ci "
        "JOIN companies c ON c.id = ci.company_id"
    )).fetchall()

    used_codes: set[str] = set()
    for row in rows:
        code = _generate_code(row.name)
        while code in used_codes:  # extremely unlikely, but guard anyway
            code = _generate_code(row.name)
        used_codes.add(code)
        conn.execute(
            sa.text("UPDATE company_invites SET short_code = :code WHERE id = :id"),
            {"code": code, "id": row.id},
        )

    # Step 3: now that every row has a value, tighten to NOT NULL and add
    # the unique constraint with an explicit name (autogenerate's `None`
    # name works but makes the downgrade fragile/ambiguous -- naming it
    # explicitly is more robust).
    op.alter_column('company_invites', 'short_code', nullable=False)
    op.create_unique_constraint('uq_company_invites_short_code', 'company_invites', ['short_code'])


def downgrade() -> None:
    op.drop_constraint('uq_company_invites_short_code', 'company_invites', type_='unique')
    op.drop_column('company_invites', 'short_code')