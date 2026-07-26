"""FastAPI dependencies: DB session, current user, role enforcement, plan gating.

Every protected route composes from these. Tenant scoping starts here: company_id
is read from the verified JWT and threaded into services — never from the request body.
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db  # re-exported for convenience
from app.core.models.company_module import CompanyModule
from app.core.models.user import User

bearer_scheme = HTTPBearer(auto_error=True)

ROLE_OWNER = "owner_admin"
ROLE_MANAGER = "manager"
ROLE_EMPLOYEE = "employee"
ALL_ROLES = (ROLE_OWNER, ROLE_MANAGER, ROLE_EMPLOYEE)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await db.get(User, int(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated")
    # Defense in depth: token tenant must match the user row.
    if user.company_id != payload.get("company_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant mismatch")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DB = Annotated[AsyncSession, Depends(get_db)]


def require_role(allowed_roles: list[str]):
    """Usage: user: User = Depends(require_role([ROLE_OWNER, ROLE_MANAGER]))"""

    async def _dep(user: CurrentUser) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return _dep


# ---------------------------------------------------------------------------
# Module gating -- flat pricing, no tiers. A company either has a module
# enabled (full access to everything in it) or doesn't (no access at all).
# Replaces the old PLAN_ORDER/PLAN_FEATURES tier-comparison system entirely
# -- there is no longer a concept of "this feature needs a higher plan,"
# since every feature within an enabled module is simply included.
# ---------------------------------------------------------------------------
ACTIVE_MODULE_STATUSES = ("active", "trialing")


def require_module_enabled(module_key: str):
    """Blocks the route unless the company has this module enabled.

    Also checks Company.active FIRST -- a manual platform-admin kill
    switch, completely independent of any module's billing status. A
    company can have every module fully paid and still be blocked if
    platform staff have manually deactivated them via the internal admin
    dashboard.

    "Enabled" means status is active/trialing AND (if current_period_end
    is set) that period hasn't passed yet -- this is what makes the
    "disable mid-month still works until the period you already paid for
    ends" rule actually take effect: disabling only flips auto_renew to
    False, it doesn't touch status or current_period_end immediately, so
    access continues correctly until a scheduled job closes it out.
    """
    async def _dep(user: CurrentUser, db: DB) -> None:
        from datetime import datetime, timezone
        from app.core.models.company import Company

        company = await db.get(Company, user.company_id)
        if company is not None and not company.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This company's access has been suspended. Contact support.",
            )

        res = await db.execute(
            select(CompanyModule).where(
                CompanyModule.company_id == user.company_id,
                CompanyModule.module_key == module_key,
            )
        )
        cm = res.scalar_one_or_none()
        if cm is None or cm.status not in ACTIVE_MODULE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"The '{module_key}' module isn't enabled for this company.",
            )
        if cm.current_period_end is not None and cm.current_period_end < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"The '{module_key}' module's paid period has ended.",
            )

    return _dep


# Kept as the same exported name every existing HR router already applies
# (dependencies=[RequireActivePlan]) -- only what it checks changed, not
# its name or how it's used, so no router file needed touching for this cutover.
RequireActivePlan = Depends(require_module_enabled("hr"))