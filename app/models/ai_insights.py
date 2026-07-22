"""AI Insights -- caching tables for the two summary types (company
overview, per-project). Entirely new/additive; nothing here touches any
existing model or table.
"""
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TenantMixin


class CompanyOverviewAnalysis(Base, PKMixin, TenantMixin):
    """One row per (company, period) -- the "whole company" summary option.
    No cooldown enforced here (unlike per-project) since generating this
    only runs a handful of aggregate queries, not one LLM call per
    employee's reports -- cheap enough not to need rate limiting."""

    __tablename__ = "company_overview_analyses"

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    narrative_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectAnalysis(Base, PKMixin, TenantMixin):
    """One row per (project, period) generation. The 1-hour cooldown is
    enforced in the service layer by checking the most recent row's
    generated_at for this project_id -- regardless of which period was
    requested -- since each generation runs one LLM call per project
    (reading through report text for every assigned employee), which is
    expensive enough to actually rate-limit, unlike the overview summary."""

    __tablename__ = "project_analyses"

    project_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    narrative_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())