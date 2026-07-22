"""Declarative base + tenant mixin. Import app.models before create_all/autogenerate."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


class PKMixin:
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TenantMixin:
    """Every tenant-scoped table carries company_id. Services must always filter on it."""

    @declared_attr
    def company_id(cls) -> Mapped[int]:
        return mapped_column(BigInteger, ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False)
