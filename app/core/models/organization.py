"""Organization -- the billing tenant. Owns the Stripe customer relationship.

One Organization can wrap multiple Companies (a company's "projects" --
e.g. one retail chain + one separate consulting arm run by the same
owner). Billing always charges the Organization's one payment method,
itemized per Company/module underneath it -- a Company never has its own
separate Stripe customer.

Every existing Company (pre-dating this table) gets exactly one
auto-generated Organization created for it during migration, so nothing
breaks for current customers -- see
app/db/migrations/versions/<next>_add_organizations.py.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin


class Organization(Base, PKMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable + SET NULL on delete: the owner User references this
    # Organization too (User.organization_id), which would otherwise be a
    # circular hard dependency between the two tables at creation time.
    owner_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL", use_alter=True)
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
