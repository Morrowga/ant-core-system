"""add organizations, company_modules, module_assignments

Revision ID: a1f9e2c7b410
Revises: cc2d72f34b01
Create Date: 2026-07-24

NOTE: written for a FRESH/EMPTY database. On a database that already has
real Company/User rows, organization_id must be added nullable-first,
backfilled with one new Organization per existing Company, THEN tightened
to NOT NULL -- see the migration plan doc for that version. Since this is
targeting a brand-new container with no existing rows, that backfill
dance is unnecessary here: organization_id can go straight to NOT NULL.
"""
"""add organizations, company_modules, module_assignments

Revision ID: a1f9e2c7b410
Revises: cc2d72f34b01
Create Date: 2026-07-24

Guarded with existence checks throughout. This matters for a reason
specific to THIS migration: 0001_initial_schema.py builds its tables from
Base.metadata.create_all(), driven by CURRENT model classes -- not a
frozen historical snapshot. Since Organization/CompanyModule/
ModuleAssignment (and Company.organization_id / User.organization_id)
are now part of the current models, 0001 ALREADY creates all of this on a
fresh database. This migration only does real work on an OLDER database
that was built before these models existed and never ran 0001 again.
Everything below checks first so it behaves correctly in both cases.
"""
from alembic import op
import sqlalchemy as sa


revision = "a1f9e2c7b410"
down_revision = "cc2d72f34b01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ---------------------------------------------------------------
    # organizations
    # ---------------------------------------------------------------
    if "organizations" not in existing_tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("owner_user_id", sa.BigInteger(), nullable=True),
            sa.Column("stripe_customer_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_organizations_stripe_customer_id", "organizations", ["stripe_customer_id"])
        op.create_foreign_key(
            "fk_organizations_owner_user_id", "organizations", "users",
            ["owner_user_id"], ["id"], ondelete="SET NULL",
        )

    # ---------------------------------------------------------------
    # companies.organization_id
    # ---------------------------------------------------------------
    company_columns = {c["name"] for c in inspector.get_columns("companies")}
    if "organization_id" not in company_columns:
        op.add_column("companies", sa.Column("organization_id", sa.BigInteger(), nullable=False))
        op.create_index("ix_companies_organization_id", "companies", ["organization_id"])
        op.create_foreign_key(
            "fk_companies_organization_id", "companies", "organizations",
            ["organization_id"], ["id"], ondelete="RESTRICT",
        )

    # ---------------------------------------------------------------
    # users.organization_id
    # ---------------------------------------------------------------
    user_columns = {c["name"] for c in inspector.get_columns("users")}
    if "organization_id" not in user_columns:
        op.add_column("users", sa.Column("organization_id", sa.BigInteger(), nullable=False))
        op.create_index("ix_users_organization_id", "users", ["organization_id"])
        op.create_foreign_key(
            "fk_users_organization_id", "users", "organizations",
            ["organization_id"], ["id"], ondelete="RESTRICT",
        )

    # ---------------------------------------------------------------
    # company_modules -- generalizes Subscription to per-module billing.
    # NOTE: this is a NEW, separate table alongside the existing
    # "subscriptions" table -- Subscription is intentionally left alone
    # and still fully functional (see app/core/models/company.py). The
    # cutover of billing/gating logic from Subscription to CompanyModule
    # is a deliberate future step, not part of this migration.
    # ---------------------------------------------------------------
    if "company_modules" not in existing_tables:
        op.create_table(
            "company_modules",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("module_key", sa.String(length=40), nullable=False),
            sa.Column("plan_tier", sa.String(length=20), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(length=64), nullable=True),
            sa.Column("stripe_subscription_item_id", sa.String(length=64), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="trialing"),
            sa.Column("seats_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("renews_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_company_modules_company_id", "company_modules", ["company_id"])
        op.create_index("ix_company_modules_stripe_subscription_id", "company_modules", ["stripe_subscription_id"])
        op.create_unique_constraint(
            "uq_company_modules_company_module", "company_modules", ["company_id", "module_key"]
        )

    # ---------------------------------------------------------------
    # module_assignments -- thin per-module extension of an existing User.
    # ---------------------------------------------------------------
    if "module_assignments" not in existing_tables:
        op.create_table(
            "module_assignments",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("company_id", sa.BigInteger(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("module_key", sa.String(length=40), nullable=False),
            sa.Column("module_role", sa.String(length=40), nullable=False),
            sa.Column("module_data_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_module_assignments_company_id", "module_assignments", ["company_id"])
        op.create_index("ix_module_assignments_user_id", "module_assignments", ["user_id"])
        op.create_unique_constraint(
            "uq_module_assignments_user_module", "module_assignments", ["company_id", "user_id", "module_key"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "module_assignments" in existing_tables:
        op.drop_table("module_assignments")
    if "company_modules" in existing_tables:
        op.drop_table("company_modules")

    user_columns = {c["name"] for c in inspector.get_columns("users")} if "users" in existing_tables else set()
    if "organization_id" in user_columns:
        op.drop_constraint("fk_users_organization_id", "users", type_="foreignkey")
        op.drop_index("ix_users_organization_id", table_name="users")
        op.drop_column("users", "organization_id")

    company_columns = {c["name"] for c in inspector.get_columns("companies")} if "companies" in existing_tables else set()
    if "organization_id" in company_columns:
        op.drop_constraint("fk_companies_organization_id", "companies", type_="foreignkey")
        op.drop_index("ix_companies_organization_id", table_name="companies")
        op.drop_column("companies", "organization_id")

    if "organizations" in existing_tables:
        op.drop_constraint("fk_organizations_owner_user_id", "organizations", type_="foreignkey")
        op.drop_table("organizations")
