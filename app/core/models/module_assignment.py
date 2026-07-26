"""ModuleAssignment -- HOW an existing person participates in a specific
module, WITHOUT duplicating their identity. User/Company/Branch are core,
shared, always exist regardless of which modules are enabled; a module
never gets its own separate "employee" table.

Not used by HR today (HR reads role directly off User.role, unchanged).
Created now, empty, so Warehouse/POS can attach role/extra-data onto an
existing User (e.g. "cashier", pin_hash) the moment they're built, with no
second migration needed to introduce the concept.
"""
from sqlalchemy import BigInteger, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, PKMixin, TenantMixin


class ModuleAssignment(Base, PKMixin, TenantMixin, CreatedAtMixin):
    __tablename__ = "module_assignments"
    __table_args__ = (
        UniqueConstraint("company_id", "user_id", "module_key", name="uq_module_assignments_user_module"),
    )

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    module_key: Mapped[str] = mapped_column(String(40), nullable=False)  # "warehouse" | "pos" | ...
    module_role: Mapped[str] = mapped_column(String(40), nullable=False)  # "cashier" | "warehouse_clerk" | ...
    # Module-specific extras that don't deserve their own column yet --
    # e.g. {"pin_hash": "...", "can_refund": false} for a POS cashier.
    module_data_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
