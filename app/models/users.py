from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, ForeignKey, JSON, Numeric, String,
                        func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class User(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="employee", nullable=False)  # owner_admin|manager|employee
    team_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # New: per-employee timezone (IANA name, e.g. "Asia/Ho_Chi_Minh"). Null =
    # falls back to the company's own timezone -- only needs to be set for
    # employees genuinely in a different timezone than the company.
    timezone: Mapped[str | None] = mapped_column(String(64))
    holiday_country: Mapped[str | None] = mapped_column(String(20))
    # New: invoicing fields.
    #   job_type -- "full_time" keeps the existing shift-based check-in/out
    #     flow completely unchanged. "part_time" removes shift-time
    #     restrictions (no early-check-in block, no shift-ended block) but
    #     only allows ONE check-in/out cycle per calendar day, enforced in
    #     AttendanceService.check_in().
    #   actual_working_hours -- True: invoices are computed from real
    #     clocked time (elapsed minus breaks, late arrival, and presence-
    #     check no-response deductions -- the same figures today_invoice()
    #     already computes per day, summed across the whole pay period).
    #     False: invoices assume the full scheduled hours for every
    #     workday in the period, minus only approved leave days -- a
    #     salary-style calculation that ignores clock-in precision
    #     entirely.
    #   hourly_fee -- only meaningful (and only shown in the UI) when the
    #     company's "invoice_enabled" setting (CompanySettings, section=
    #     "invoicing") is on. Nullable: a company can have invoicing on
    #     company-wide but not yet have set a rate for every employee.
    job_type: Mapped[str] = mapped_column(String(20), default="full_time", nullable=False)
    actual_working_hours: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hourly_fee: Mapped[float | None] = mapped_column(Numeric(10, 2))


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
    # New: structured payload (e.g. {"type": "desk_location_request",
    # "employee_id": "42", "request_id": "7"}) -- lets the dashboard's
    # notification bell navigate somewhere specific on click instead of
    # only being able to mark read. Was being passed into
    # notification_service.send()'s extra_data parameter this whole time
    # but silently dropped, since no column existed to store it in.
    extra_data_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class NotificationPreference(Base, PKMixin):
    """Per-user notification mute settings (non-critical categories only).

    The list of categories that can never be muted is hardcoded in
    app/services/notifications.py::NON_MUTABLE_CATEGORIES.
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    muted_categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)