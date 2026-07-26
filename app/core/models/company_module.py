"""CompanyModule -- which modules a Company has enabled, and their billing
state. Generalizes the old Subscription table (which assumed a Company
only ever had ONE thing to pay for) to support multiple independently
billable modules per Company: "hr", "warehouse", "pos", etc.

Every pre-existing Subscription row becomes a CompanyModule row with
module_key="hr" during migration -- same fields, same meaning, just
re-scoped. See app/db/migrations/versions/<next>_add_company_modules.py.

Billing rule (confirmed in design discussion): enabling a module commits
the company to paying for the current full billing period -- no proration,
no refund for disabling partway through. Disabling just sets
auto_renew=False; access continues until current_period_end, then the
module silently stops renewing. Re-enabling before current_period_end has
passed simply flips auto_renew back to True (no new charge, since that
period is already paid for).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class CompanyModule(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "company_modules"
    __table_args__ = (UniqueConstraint("company_id", "module_key", name="uq_company_modules_company_module"),)

    module_key: Mapped[str] = mapped_column(String(40), nullable=False)  # "hr" | "warehouse" | "pos" | ...
    # Only meaningful for modules that have internal tiers (HR does, via
    # PLAN_FEATURES gating). A module with no tiering concept (e.g. a flat
    # Warehouse price) can leave this null.
    plan_tier: Mapped[str | None] = mapped_column(String(20))  # startup|mid|enterprise, HR-specific today
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="trialing", nullable=False)  # trialing|active|past_due|cancelled
    seats_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # False once the Owner has disabled this module -- access continues
    # until current_period_end, then status flips to "cancelled" by a
    # scheduled job rather than instantly on the disable click.
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    renews_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
