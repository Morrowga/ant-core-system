"""Core, module-independent identity models. Moved here unchanged from
the old app/models/users.py as part of the Organization/module
restructuring. User/Team/Consent/DeviceToken/Notification/
NotificationPreference are shared platform infrastructure -- they exist
regardless of which modules a Company has enabled, and no module owns or
duplicates them. A module that needs to know "how does this person
participate in MY module specifically" attaches a thin ModuleAssignment
row (see app/core/models/module_assignment.py) rather than defining its
own separate person record.
"""
from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, JSON, Numeric, String,
                        func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class User(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "users"

    # Override TenantMixin's NOT NULL company_id specifically for User.
    # An Organization's owner_admin can now exist before any Company does
    # -- registration creates the Organization + owner User only; the
    # Company is created afterward via POST /organizations/{id}/companies,
    # which is what sets this. Every OTHER tenant-scoped table (HR data,
    # CompanyInvite, CompanyModule, etc.) keeps TenantMixin's normal NOT
    # NULL company_id unchanged -- those rows only ever get created once a
    # Company already exists, so there's nothing to make nullable there.
    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )

    # New: which Organization this person belongs to -- added alongside
    # Company.organization_id as part of the same migration. Nullable at
    # the DB level only during the backfill window (add nullable, backfill
    # from this User's own Company.organization_id, then tighten to NOT
    # NULL) -- see app/db/migrations/versions/<next>_add_organizations.py.
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, nullable=False
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)  # owner_admin|manager|employee
    team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64))
    holiday_country: Mapped[str | None] = mapped_column(String(20))
    # NOTE: job_type / actual_working_hours / hourly_fee below are
    # HR-invoicing-shaped fields living on the core User row. Left in
    # place for this restructuring pass (moving them would mean either
    # duplicating identity data into modules/hr or a much bigger
    # normalization effort) -- flagged as a candidate for a future
    # ModuleAssignment.module_data_json migration once a second module
    # actually needs its own, different notion of "job type."
    job_type: Mapped[str] = mapped_column(String(20), default="full_time", nullable=False)
    actual_working_hours: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hourly_fee: Mapped[float | None] = mapped_column(Numeric(10, 2))
    language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)


class Team(Base, PKMixin, TenantMixin):
    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    manager_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL", use_alter=True))


class Consent(Base, PKMixin):
    __tablename__ = "consents"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # location|health|notifications
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceToken(Base, PKMixin):
    __tablename__ = "device_tokens"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    fcm_token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)  # mobile|web
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(2000), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_data_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NotificationPreference(Base, PKMixin):
    """Per-user notification mute settings (non-critical categories only).

    The list of categories that can never be muted is hardcoded in
    app/core/services/notifications.py::NON_MUTABLE_CATEGORIES.
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    muted_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)