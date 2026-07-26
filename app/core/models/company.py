"""Core, module-independent company/tenant models. Moved here unchanged
from the old app/models/company.py as part of the Organization/module
restructuring -- no field or behavior changes in this file.

NOTE on Subscription: this is deliberately kept as-is here, still pointing
at the "subscriptions" table, rather than being cut over to the new
CompanyModule table (see app/core/models/company_module.py) in this same
pass. Every existing require_active_subscription()/require_plan_feature()/
billing.py call site still reads Subscription exactly as before -- cutting
those over to CompanyModule is flagged as the next incremental step, done
deliberately and separately (with real DB testing), not rushed in the same
change as a pure folder/import restructuring.
"""
from datetime import datetime
from datetime import date as date_type

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class Company(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "companies"

    # New: which Organization (the billing tenant) this Company -- i.e.
    # "project" -- belongs to. Nullable at the model level only during the
    # migration window; the DB column itself is added nullable-first, then
    # backfilled, then tightened to NOT NULL by the migration (see
    # app/db/migrations/versions/<next>_add_organizations.py). By the time
    # this code is deployed the column is NOT NULL in the database.
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(1024))
    industry: Mapped[str | None] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)  # IANA tz name
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    working_hours_start: Mapped[str] = mapped_column(String(5), default="09:00")  # "HH:MM"
    working_hours_end: Mapped[str] = mapped_column(String(5), default="18:00")
    workdays: Mapped[str] = mapped_column(String(32), default="mon,tue,wed,thu,fri")  # csv of weekday codes
    working_hours_mode: Mapped[str] = mapped_column(String(20), default="company_timezone", nullable=False)
    # Manual platform-admin kill switch -- independent of Stripe/plan
    # status and independent of any per-module CompanyModule status too.
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CompanyInvite(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "company_invites"

    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)
    team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="SET NULL"))
    timezone: Mapped[str | None] = mapped_column(String(64))
    holiday_country: Mapped[str | None] = mapped_column(String(20))
    job_type: Mapped[str] = mapped_column(String(20), default="full_time", nullable=False)
    actual_working_hours: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hourly_fee: Mapped[float | None] = mapped_column(Numeric(10, 2))
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    short_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)


class Subscription(Base, PKMixin, TenantMixin, CreatedAtMixin):
    """DEPRECATED shape, kept functioning as-is. Will be superseded by
    CompanyModule (module_key="hr") once billing/gating call sites are
    deliberately cut over -- not part of this restructuring pass."""

    __tablename__ = "subscriptions"

    plan_tier: Mapped[str] = mapped_column(String(20), default="startup", nullable=False)  # startup|mid|enterprise
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="trialing", nullable=False)
    seats_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompanySettings(Base, PKMixin, TenantMixin):
    """One row per (company, section); JSON blob per section keeps settings flexible.

    Platform-locked behaviours (overtime mandatory-report-to-close, harassment->Owner-only
    routing, no raw health data to non-owning roles) are NOT stored here — they are
    hardcoded in the service layer by design.
    """

    __tablename__ = "company_settings"

    section: Mapped[str] = mapped_column(String(40), nullable=False)  # attendance|reporting|alerts|health|...
    data_json: Mapped[dict] = mapped_column(__import__("sqlalchemy").JSON, default=dict, nullable=False)


class Holiday(Base, PKMixin, TenantMixin):
    """Company-owned holiday calendar. Seeded from built-in country sets
    (see app/core/holiday_seed_data.py) but fully owner-editable afterward --
    seeding just inserts starting rows into this same table, it does not
    create a separate immutable reference."""

    __tablename__ = "holidays"

    country_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # e.g. "myanmar", "japan", or "all"
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class PlatformAdmin(Base, PKMixin, CreatedAtMixin):
    """Your own internal staff -- completely separate from the customer
    User model. Deliberately has NO company_id/tenant scoping at all,
    since the entire point is cross-company visibility that no customer
    role (owner_admin/manager/employee) should ever have. Its own login,
    its own JWT flow (see app/core/admin_auth.py), fully independent from
    the customer-facing auth system."""

    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SupportTicket(Base, PKMixin, TenantMixin, CreatedAtMixin):
    """A customer company's support request TO Ants -- distinct from the
    existing employee-to-manager Feedback feature (that's internal to one
    company; this is a company reaching out to the platform operator).
    Submitted by an Owner from the regular customer dashboard, viewed and
    managed by platform staff in the new internal admin app."""

    __tablename__ = "support_tickets"

    submitted_by_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(String(4000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|in_progress|resolved
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_admin_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("platform_admins.id", ondelete="SET NULL")
    )
