"""Alerts, knowledge, feedback, recognition, certificates, goals, onboarding, AI logs."""
from datetime import date, datetime

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey,
                        Integer, String, Text, func)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class Alert(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "alerts"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)  # away_from_desk|missed_check_in|...
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)  # open|acknowledged|escalated
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertSetting(Base, PKMixin, TenantMixin):
    __tablename__ = "alert_settings"

    type: Mapped[str] = mapped_column(String(40), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    escalation_delay_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    notify_roles: Mapped[str] = mapped_column(String(60), default="manager,owner_admin", nullable=False)


class KnowledgePost(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "knowledge_posts"

    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[str] = mapped_column(String(20), default="knowledge", nullable=False)
    category: Mapped[str | None] = mapped_column(String(60), index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_acknowledge: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ack_deadline_days: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # soft delete


class KnowledgeComment(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "knowledge_comments"

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_posts.id", ondelete="CASCADE"), index=True, nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeAcknowledgment(Base, PKMixin):
    __tablename__ = "knowledge_acknowledgments"

    post_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("knowledge_posts.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackTicket(Base, PKMixin, TenantMixin, CreatedAtMixin):
    """user_id nullable: anonymous tickets NEVER store the author (rule 10).

    Anonymity hardening: created_at is truncated to the hour at insert time for
    anonymous tickets so timestamps can't be cross-referenced with attendance
    or location pings to de-anonymize the author.
    """

    __tablename__ = "feedback_tickets"

    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True, nullable=False)  # general|workload|harassment|...
    message: Mapped[str] = mapped_column(Text, nullable=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)


class Recognition(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "recognitions"

    given_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    report_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("reports.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class Certificate(Base, PKMixin):
    """Auto-issued by Celery beat (rule 6). No admin approval/edit endpoint exists."""

    __tablename__ = "certificates"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)  # monthly|yearly
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    data_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(1024))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invoice(Base, PKMixin, TenantMixin):
    """Generated on-demand (Owner clicks "Produce invoices for all" on the
    dashboard's new Invoice List page), via a queued Celery task -- unlike
    Certificate, this is NEVER auto-scheduled. One row per (employee, pay
    period). hourly_fee, total_hours, and actual_working_hours are all
    snapshotted at generation time rather than read live off the User row
    later, so a subsequent rate change or toggle flip never silently
    alters an already-generated invoice."""

    __tablename__ = "invoices"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    hourly_fee: Mapped[float] = mapped_column(Float, nullable=False)
    total_hours: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    # Snapshot of which calculation mode produced this invoice -- lets the
    # detail view explain itself ("calculated from actual clocked hours"
    # vs "calculated from scheduled hours minus leave") without depending
    # on the User row's CURRENT setting, which may have changed since.
    actual_working_hours: Mapped[bool] = mapped_column(Boolean, nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(String(1024))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OnboardingChecklistItem(Base, PKMixin, TenantMixin):
    __tablename__ = "onboarding_checklist_items"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(30), default="task", nullable=False)  # task|read|watch
    linked_knowledge_post_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("knowledge_posts.id", ondelete="SET NULL"))
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    order: Mapped[int] = mapped_column("order_index", Integer, default=0, nullable=False)  # "order" is reserved-ish; column named order_index


class EmployeeOnboardingProgress(Base, PKMixin):
    __tablename__ = "employee_onboarding_progress"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    checklist_item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("onboarding_checklist_items.id", ondelete="CASCADE"), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIQueryLog(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "ai_queries_log"

    asked_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    matched_query_type: Mapped[str | None] = mapped_column(String(60))
    parameters_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)


class AIWorkloadAnalysis(Base, PKMixin, CreatedAtMixin):
    __tablename__ = "ai_workload_analysis"

    report_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reports.id", ondelete="CASCADE"), unique=True, nullable=False)
    hours: Mapped[float] = mapped_column(Float, nullable=False)
    ai_pace_label: Mapped[str] = mapped_column(String(30), nullable=False)  # light|steady|heavy|unclear
    ai_reasoning_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)

class HealthCheckinPrompt(Base, PKMixin, TenantMixin, CreatedAtMixin):
    """One row per reminder actually SENT (sleep_checkin at check-in,
    mood_water_checkin every ~2h during an active session -- see
    health_reminders.py). `responded_at` stays null until the user answers
    via the matching mobile quick-check-in screen, which is what lets the
    Health tab show "last unanswered prompt" and gates report submission
    on everything being answered first."""

    __tablename__ = "health_checkin_prompts"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # sleep_checkin | mood_water_checkin
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))