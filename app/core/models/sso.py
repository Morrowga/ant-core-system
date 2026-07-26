"""Single-use SSO handoff codes.

Core Dashboard issues one when an already-authenticated user clicks
"Enter" on an enabled module; the target module's own frontend (HR
Dashboard today, Warehouse/POS later) exchanges it for a normal token
pair on load. This is how a user who's logged into Core Dashboard lands
already-authenticated on a completely separate frontend/subdomain,
without re-entering credentials.

Deliberately NOT tenant-scoped via TenantMixin: a code identifies a USER
(who already carries their own company_id/organization_id/role once
looked up), not a company-owned data row -- same reasoning as
Consent/DeviceToken in app/core/models/user.py.

Short-lived and single-use by design (see app/core/services/sso.py):
~30 second expiry, and used_at is set the moment it's redeemed so a
captured/replayed code can't be exchanged twice.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class SsoCode(Base, PKMixin):
    __tablename__ = "sso_codes"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))