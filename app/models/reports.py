from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class Project(Base, PKMixin, TenantMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # New: financials. deal_price is displayed using the company's own
    # currency setting (Settings > Profile) -- no separate per-project
    # currency field, to avoid ever mixing currencies within one company's
    # figures. Labor cost is NOT stored here -- it's computed on demand
    # from Report.hours (grouped by user, filtered to this project) times
    # each employee's hourly_fee, since reports already require picking a
    # project at submission time and are the natural, existing source of
    # "how many hours did this person spend on this project" -- no need to
    # reference invoicing's actual/scheduled toggle or pay-period cutoffs
    # at all for this purpose.
    deal_price: Mapped[float | None] = mapped_column(Float)
    estimated_start_date: Mapped[date | None] = mapped_column(Date)
    estimated_end_date: Mapped[date | None] = mapped_column(Date)
    # New: separate from `active` -- active/inactive controls whether a
    # project is archived (hidden from the default list, can't be
    # assigned/reported against going forward), while completed_at tracks
    # whether the WORK is actually done. A project can pass its estimated
    # end date and keep accumulating hours/cost indefinitely with no
    # signal that anything's off; this is what lets the UI show "overdue
    # by N days" until someone explicitly marks it complete, and stop
    # counting once they do.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectExpense(Base, PKMixin, CreatedAtMixin):
    """Custom additional expenses beyond computed labor cost (e.g.
    software licenses, travel, contractor invoices) -- added manually by
    an Owner/Manager, factored into the project's total expenses and
    profit calculation alongside the auto-computed labor cost."""

    __tablename__ = "project_expenses"

    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    added_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ProjectAssignment(Base, PKMixin):
    """New: which employees are assigned to a project. Owner/Manager see
    and manage every project regardless of assignment (unrestricted,
    matching how they already access every other resource company-wide) --
    this only restricts what EMPLOYEES see/can pick from when submitting a
    report (see ReportService.list_projects())."""

    __tablename__ = "project_assignments"

    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)


class Report(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "reports"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    report_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    editable_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # rule 4


class ReportComment(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "report_comments"

    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), index=True, nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)


class WorkThread(Base, PKMixin):
    __tablename__ = "work_threads"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # active|stale|closed


class WorkThreadEntry(Base, PKMixin):
    __tablename__ = "work_thread_entries"

    thread_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("work_threads.id", ondelete="CASCADE"), index=True, nullable=False)
    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), index=True, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float)


class ReportEmbedding(Base, PKMixin):
    """pgvector-backed embedding per report summary (text-embedding-3-small, 1536 dims)."""

    __tablename__ = "report_embeddings"

    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), unique=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)


class OvertimeSession(Base, PKMixin):
    __tablename__ = "overtime_sessions"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="SET NULL"))
    initiated_by: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("overtime_requests.id", ondelete="SET NULL"))  # <-- add this line
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hours: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    ai_summary: Mapped[str | None] = mapped_column(Text)


class OvertimeRequest(Base, PKMixin, CreatedAtMixin):
    """Submitted any day, ahead of time. An OvertimeSession can only be
    started (see OvertimeService.start()) if an approved request exists for
    today -- self-initiated instant-start no longer exists."""
 
    __tablename__ = "overtime_requests"
 
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    requested_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_start_time: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM"
    planned_end_time: Mapped[str] = mapped_column(String(5), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending|approved|rejected
    decided_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))