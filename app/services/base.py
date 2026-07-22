"""Base tenant-scoped service/repository pattern (multi-tenancy rule).

Every domain service inherits TenantService. `company_id` comes from the
authenticated user (i.e. the verified JWT) at construction time — routers never
accept a company_id from the client. All query helpers automatically inject the
tenant filter so it cannot be forgotten per-endpoint.

For tables that carry company_id directly, use `tenant_select(Model)`.
For user-owned tables (attendance, reports, health...) that hang off users.id,
use `tenant_select_via_user(Model)` which joins through users to enforce the
tenant boundary at the SQL level.
"""
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User


class TenantService:
    def __init__(self, db: AsyncSession, current_user: User):
        self.db = db
        self.current_user = current_user
        self.company_id: int = current_user.company_id  # derived from JWT-authenticated user only

    def tenant_select(self, model) -> Select:
        """SELECT on a table that has a company_id column, pre-filtered to this tenant."""
        return select(model).where(model.company_id == self.company_id)

    def tenant_select_via_user(self, model, user_fk_attr: str = "user_id") -> Select:
        """SELECT on a user-owned table, joined through users to enforce tenant scope."""
        fk = getattr(model, user_fk_attr)
        return select(model).join(User, User.id == fk).where(User.company_id == self.company_id)

    async def assert_user_in_tenant(self, user_id: int) -> User:
        """Load a user and verify they belong to the caller's company. 404 otherwise."""
        from fastapi import HTTPException

        target = await self.db.get(User, user_id)
        if target is None or target.company_id != self.company_id:
            raise HTTPException(status_code=404, detail="User not found")
        return target

    def is_manager_of(self, target: User) -> bool:
        return (
            self.current_user.role == "manager"
            and target.team_id is not None
            and target.team_id == self.current_user.team_id
        )

    def can_view_employee(self, target: User) -> bool:
        """owner_admin: whole company; manager: own team; employee: self only."""
        if self.current_user.role == "owner_admin":
            return True
        if self.current_user.role == "manager":
            return target.id == self.current_user.id or self.is_manager_of(target)
        return target.id == self.current_user.id
