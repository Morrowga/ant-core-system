from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class AttendanceSession(Base, PKMixin):
    __tablename__ = "attendance_sessions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    check_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    desk_lat: Mapped[float | None] = mapped_column(Float)
    desk_lng: Mapped[float | None] = mapped_column(Float)
    last_health_prompt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_minutes: Mapped[int | None] = mapped_column(Integer)
    early_checkout_minutes: Mapped[int | None] = mapped_column(Integer)
    # Set at check-in time by comparing coordinates against the user's
    # saved DeskLocation (300m radius). Lets the dashboard query "which
    # sessions started outside the usual desk area" directly on the session,
    # independent of whether a WorkOutsideOverride was ever confirmed for
    # that date.
    checked_in_outside_desk: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class BreakSession(Base, PKMixin):
    __tablename__ = "break_sessions"

    attendance_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PresenceCheckPrompt(Base, PKMixin, TenantMixin):
    """Replaces GPS-based away-from-desk tracking specifically for days
    marked "working outside" (location isn't a meaningful signal there).
    Every ~40 minutes, sends a "still working?" yes/no check; if unanswered
    within 10 minutes, that ~40-minute interval is auto-marked as
    unverified/deducted from worked time -- a manager can revert the
    deduction (e.g. if it turns out to be a false positive)."""

    __tablename__ = "presence_check_prompts"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    attendance_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response: Mapped[str | None] = mapped_column(String(5))  # "yes" | "no"
    interval_minutes: Mapped[int] = mapped_column(Integer, default=40, nullable=False)  # the gap this prompt covers
    deducted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # true if no response within 10 min
    reverted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeskLocation(Base, PKMixin):
    __tablename__ = "desk_locations"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkOutsideOverride(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "work_outside_overrides"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    # created_at (from CreatedAtMixin) is the start time. ended_at is set
    # when cancel_work_outside() turns it back off -- null while still
    # active, so the dashboard can show "started at X" alone for an
    # ongoing one, or "X to Y" once it's been turned off.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LocationPing(Base, PKMixin):
    __tablename__ = "location_pings"

    attendance_session_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LeaveRequest(Base, PKMixin):
    __tablename__ = "leave_requests"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # annual|sick|unpaid|other
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Optional time-of-day bounds, for partial-day leave (e.g. "2 hours for
    # a bank errand"). Null on both = a normal whole-day leave. If set,
    # start_date should equal end_date (validated at the API layer).
    start_time: Mapped[str | None] = mapped_column(String(5))  # "HH:MM"
    end_time: Mapped[str | None] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|approved|rejected
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class DeskLocationRequest(Base, PKMixin, TenantMixin, CreatedAtMixin):
    """A pending change to an employee's desk location, awaiting Owner/
    Manager approval. Approving creates a new DeskLocation row (the actual
    history table) and marks this approved; rejecting just marks it
    rejected, nothing else happens."""
    __tablename__ = "desk_location_requests"
 
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|approved|rejected
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))