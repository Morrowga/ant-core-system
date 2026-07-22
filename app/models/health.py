from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class HealthLog(Base, PKMixin):
    """Raw per-user health data. NEVER exposed row-level to owner_admin/manager (rule 5).

    Only app/services/health.py may query this table, and its team-facing functions
    return aggregates with a minimum group size.
    """

    __tablename__ = "health_logs"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)  # water|mood|steps|sleep|break_ack
    value: Mapped[float] = mapped_column(Float, nullable=False)  # ml, mood 1-5, step count, hours, 1=ack
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
